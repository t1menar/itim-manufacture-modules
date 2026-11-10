package messaging

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/t1menar/manufacture/core/internal/db"
)

// Outcome values stored in the inbox.
const (
	Applied  = "applied"
	Stale    = "stale"
	Conflict = "conflict"
	Invalid  = "invalid"
)

// Handler applies one message inside the consumer transaction and returns the inbox outcome.
// A returned error rolls the transaction back and the message is redelivered (bounded by the
// queue delivery limit, then dead-lettered).
type Handler func(ctx context.Context, tx pgx.Tx, e Envelope) (string, error)

// Consumer processes a queue with manual acks: inbox insert + effect commit first, ack after.
type Consumer struct {
	once     sync.Once // guards defaults; the value is shared by goroutines
	Pool     *pgxpool.Pool
	Name     string // inbox consumer name, e.g. core.job-events
	Queue    string
	Handler  Handler
	Prefetch int
	// MaxAttempts bounds handler failures per message before it is dead-lettered. RabbitMQ 4
	// does not count nack-requeue toward x-delivery-limit, so the consumer counts failures itself
	// (in memory; crash redeliveries are still counted by the broker's x-delivery-count).
	MaxAttempts int
	failures    map[string]int
	Log         *slog.Logger
	// RetryDelay grows with the delivery count before a requeue, so a failing message
	// cannot spin in a hot loop. The wait is a timer, it does not block other messages.
	RetryDelay func(deliveryCount int64) time.Duration

	// Test hooks simulating a crash: BeforeCommit returns an error after the effect but before
	// commit; AfterCommit returns an error after commit but before ack. In both cases the
	// channel is closed without ack, as a dead process would.
	BeforeCommit func(Envelope) error
	AfterCommit  func(Envelope) error
}

var errSimulatedCrash = errors.New("simulated consumer crash")

func (c *Consumer) defaults() { c.once.Do(c.setDefaults) }

func (c *Consumer) setDefaults() {
	if c.Prefetch == 0 {
		// > 1 so a message waiting for its delayed requeue does not stall the queue.
		c.Prefetch = 16
	}
	if c.Log == nil {
		c.Log = slog.Default()
	}
	if c.MaxAttempts == 0 {
		c.MaxAttempts = 5
	}
	c.failures = map[string]int{}
	if c.RetryDelay == nil {
		c.RetryDelay = func(n int64) time.Duration { return min(time.Duration(n+1)*200*time.Millisecond, 5*time.Second) }
	}
}

// Consume runs until ctx is done or the channel closes. It returns errSimulatedCrash-wrapped
// errors when a hook simulated a crash.
func (c *Consumer) Consume(ctx context.Context, conn *amqp.Connection) error {
	c.defaults()
	ch, err := conn.Channel()
	if err != nil {
		return err
	}
	// Closing the channel returns every unacked delivery to the queue. The close runs while
	// the delivery channel is drained, otherwise the library can block on an unread delivery.
	shutdown := func(deliveries <-chan amqp.Delivery) {
		go func() { _ = ch.Close() }()
		for range deliveries {
		}
	}
	if err := ch.Qos(c.Prefetch, 0, false); err != nil {
		_ = ch.Close()
		return err
	}
	deliveries, err := ch.Consume(c.Queue, "", false, false, false, false, nil)
	if err != nil {
		_ = ch.Close()
		return err
	}
	for {
		select {
		case <-ctx.Done():
			shutdown(deliveries)
			return nil
		case d, ok := <-deliveries:
			if !ok {
				return errors.New("delivery channel closed")
			}
			if err := c.handle(ctx, d); err != nil {
				if errors.Is(err, errSimulatedCrash) {
					shutdown(deliveries) // unacked deliveries return to the queue
					return err
				}
				c.Log.Warn("consume", "err", err)
				if ch.IsClosed() {
					shutdown(deliveries)
					return err
				}
			}
		}
	}
}

func deliveryCount(d amqp.Delivery) int64 {
	switch v := d.Headers["x-delivery-count"].(type) {
	case int64:
		return v
	case int32:
		return int64(v)
	case int:
		return int64(v)
	}
	return 0
}

func (c *Consumer) handle(ctx context.Context, d amqp.Delivery) error {
	env, err := Parse(d.Body)
	if err == nil && d.MessageId != "" && d.MessageId != env.MessageID.String() {
		err = fmt.Errorf("AMQP message_id %q differs from envelope", d.MessageId)
	}
	if err != nil {
		// Poison: it can never be applied. Dead-letter it without requeue.
		c.Log.Error("poison message dead-lettered", "err", err)
		return d.Nack(false, false)
	}
	duplicate := false
	err = db.WithTx(ctx, c.Pool, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `INSERT INTO inbox (consumer, message_id, type, outcome) VALUES ($1, $2, $3, 'applied')
			ON CONFLICT DO NOTHING`, c.Name, env.MessageID, env.Type)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			duplicate = true
			return nil
		}
		outcome, err := c.Handler(ctx, tx, env)
		if err != nil {
			return err
		}
		if outcome != Applied {
			if _, err := tx.Exec(ctx, `UPDATE inbox SET outcome = $3 WHERE consumer = $1 AND message_id = $2`,
				c.Name, env.MessageID, outcome); err != nil {
				return err
			}
		}
		if c.BeforeCommit != nil {
			if err := c.BeforeCommit(env); err != nil {
				return fmt.Errorf("%w: %v", errSimulatedCrash, err)
			}
		}
		return nil
	})
	if errors.Is(err, errSimulatedCrash) {
		return err
	}
	if err != nil {
		key := env.MessageID.String()
		c.failures[key]++
		n := max(int64(c.failures[key]), deliveryCount(d)+1)
		if n >= int64(c.MaxAttempts) {
			delete(c.failures, key)
			c.Log.Error("message failed too often; dead-lettered", "message_id", env.MessageID, "attempts", n, "err", err)
			return d.Nack(false, false)
		}
		// Requeue after a back-off without blocking this consumer: other messages keep flowing
		// (up to Prefetch unacked deliveries) while this one waits. If the channel closes first,
		// the broker returns the delivery to the queue anyway.
		delay := c.RetryDelay(n)
		c.Log.Warn("message processing failed; requeue", "message_id", env.MessageID, "delivery_count", n, "delay", delay, "err", err)
		time.AfterFunc(delay, func() {
			if err := d.Nack(false, true); err != nil {
				c.Log.Warn("delayed requeue failed; broker redelivers on channel close", "message_id", env.MessageID, "err", err)
			}
		})
		return nil
	}
	delete(c.failures, env.MessageID.String())
	if duplicate {
		c.Log.Info("duplicate message acked without effect", "message_id", env.MessageID)
	}
	if c.AfterCommit != nil {
		if err := c.AfterCommit(env); err != nil {
			return fmt.Errorf("%w: %v", errSimulatedCrash, err)
		}
	}
	return d.Ack(false)
}
