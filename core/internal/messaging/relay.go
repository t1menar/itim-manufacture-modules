package messaging

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	amqp "github.com/rabbitmq/amqp091-go"
)

// Relay publishes pending outbox rows with publisher confirms and the mandatory flag.
// A row is marked sent only after the broker confirmed it; a crash between confirm and the
// mark re-publishes the same message_id, which consumers deduplicate.
type Relay struct {
	once        sync.Once // guards defaults; the value is shared by goroutines
	Pool        *pgxpool.Pool
	Worker      string        // lease owner id, e.g. hostname/pid/n
	Lease       time.Duration // claim lease; expired leases of a dead relay are taken over
	Batch       int
	MaxAttempts int // after this many failed publishes the row becomes 'dead' (alert, manual action)
	Log         *slog.Logger

	// AfterConfirm is a test hook called after the broker confirm and before the row is marked
	// sent. Returning an error simulates a crash in that window.
	AfterConfirm func(messageID uuid.UUID) error
}

var errUnroutable = errors.New("unroutable: no queue bound for routing key")

type claimed struct {
	id         int64
	messageID  uuid.UUID
	exchange   string
	routingKey string
	body       []byte
	attempts   int
}

func (r *Relay) defaults() { r.once.Do(r.setDefaults) }

func (r *Relay) setDefaults() {
	if r.Lease == 0 {
		r.Lease = 30 * time.Second
	}
	if r.Batch == 0 {
		r.Batch = 50
	}
	if r.MaxAttempts == 0 {
		r.MaxAttempts = 20
	}
	if r.Log == nil {
		r.Log = slog.Default()
	}
}

// Backoff for failed publishes: 1 s, 2 s, 4 s ... capped at 5 min.
func Backoff(attempt int) time.Duration {
	d := time.Second << min(attempt, 9)
	return min(d, 5*time.Minute)
}

func (r *Relay) claim(ctx context.Context) ([]claimed, error) {
	rows, err := r.Pool.Query(ctx, `
		UPDATE outbox SET locked_by = $1, locked_until = now() + make_interval(secs => $2)
		WHERE id IN (
			SELECT id FROM outbox
			WHERE status = 'pending' AND next_attempt_at <= now()
			  AND (locked_until IS NULL OR locked_until < now())
			ORDER BY id LIMIT $3 FOR UPDATE SKIP LOCKED)
		RETURNING id, message_id, exchange, routing_key, body::text, publish_attempts`,
		r.Worker, r.Lease.Seconds(), r.Batch)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []claimed
	for rows.Next() {
		var c claimed
		var body string
		if err := rows.Scan(&c.id, &c.messageID, &c.exchange, &c.routingKey, &body, &c.attempts); err != nil {
			return nil, err
		}
		c.body = []byte(body)
		out = append(out, c)
	}
	return out, rows.Err()
}

// RunOnce claims one batch and publishes it on a fresh confirm channel. It returns the number
// of rows marked sent.
func (r *Relay) RunOnce(ctx context.Context, conn *amqp.Connection) (int, error) {
	r.defaults()
	rows, err := r.claim(ctx)
	if err != nil || len(rows) == 0 {
		return 0, err
	}
	ch, err := conn.Channel()
	if err != nil {
		r.releaseAll(ctx, rows, err)
		return 0, err
	}
	defer ch.Close()
	if err := ch.Confirm(false); err != nil {
		r.releaseAll(ctx, rows, err)
		return 0, err
	}
	returns := ch.NotifyReturn(make(chan amqp.Return, 1))
	sent := 0
	for i, c := range rows {
		if err := r.publishOne(ctx, ch, returns, c); err != nil {
			if errors.Is(err, errCrash) {
				return sent, err // simulated crash: leave the lease to expire
			}
			r.fail(ctx, c, err)
			if ch.IsClosed() {
				r.releaseAll(ctx, rows[i+1:], err)
				return sent, err
			}
			continue
		}
		sent++
	}
	return sent, nil
}

var errCrash = errors.New("simulated crash")

func (r *Relay) publishOne(ctx context.Context, ch *amqp.Channel, returns <-chan amqp.Return, c claimed) error {
	pctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	dc, err := ch.PublishWithDeferredConfirmWithContext(pctx, c.exchange, c.routingKey, true, false, amqp.Publishing{
		MessageId:    c.messageID.String(),
		ContentType:  "application/json",
		DeliveryMode: amqp.Persistent,
		Timestamp:    time.Now(),
		Body:         c.body,
	})
	if err != nil {
		return fmt.Errorf("publish: %w", err)
	}
	acked, err := dc.WaitContext(pctx)
	if err != nil {
		return fmt.Errorf("confirm: %w", err)
	}
	if !acked {
		return errors.New("broker nacked the message")
	}
	// basic.return is delivered before the confirm for the same message.
	select {
	case ret := <-returns:
		if ret.MessageId == c.messageID.String() {
			return errUnroutable
		}
	default:
	}
	if r.AfterConfirm != nil {
		if err := r.AfterConfirm(c.messageID); err != nil {
			return errCrash
		}
	}
	tag, err := r.Pool.Exec(ctx, `UPDATE outbox SET status = 'sent', sent_at = now(), locked_by = NULL, locked_until = NULL
		WHERE id = $1 AND locked_by = $2 AND status = 'pending'`, c.id, r.Worker)
	if err != nil {
		return fmt.Errorf("mark sent: %w", err)
	}
	if tag.RowsAffected() == 0 {
		r.Log.Warn("outbox lease lost before mark; another relay will re-publish the same message_id", "message_id", c.messageID)
	}
	return nil
}

func (r *Relay) fail(ctx context.Context, c claimed, cause error) {
	n := c.attempts + 1
	status := "pending"
	if n >= r.MaxAttempts {
		status = "dead"
	}
	_, err := r.Pool.Exec(ctx, `UPDATE outbox SET publish_attempts = $3, last_error = $4, status = $5,
		next_attempt_at = now() + make_interval(secs => $6), locked_by = NULL, locked_until = NULL
		WHERE id = $1 AND locked_by = $2`, c.id, r.Worker, n, cause.Error(), status, Backoff(n).Seconds())
	if err != nil {
		r.Log.Error("outbox fail update", "err", err)
	}
	r.Log.Warn("outbox publish failed", "message_id", c.messageID, "attempt", n, "status", status, "err", cause)
}

func (r *Relay) releaseAll(ctx context.Context, rows []claimed, cause error) {
	for _, c := range rows {
		r.fail(ctx, c, cause)
	}
}

// Run publishes until ctx is done, polling every interval.
func (r *Relay) Run(ctx context.Context, conn func() *amqp.Connection, interval time.Duration) {
	r.defaults()
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		if c := conn(); c != nil && !c.IsClosed() {
			for {
				n, err := r.RunOnce(ctx, c)
				if err != nil {
					r.Log.Warn("relay batch", "err", err)
				}
				if n < r.Batch || err != nil {
					break
				}
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}
