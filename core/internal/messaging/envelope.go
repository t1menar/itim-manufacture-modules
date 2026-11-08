// Package messaging implements the RabbitMQ transport of core-04 §15: envelope, topology,
// transactional outbox relay with publisher confirms, and an inbox-deduplicating consumer.
// Delivery is at-least-once; nothing here promises exactly-once.
package messaging

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// Envelope mirrors core/schemas/events/envelope.json.
type Envelope struct {
	MessageID     uuid.UUID       `json:"message_id"`
	Type          string          `json:"type"`
	SchemaVersion int             `json:"schema_version"`
	OccurredAt    time.Time       `json:"occurred_at"`
	Producer      string          `json:"producer"`
	ProductionID  *uuid.UUID      `json:"production_id,omitempty"`
	Traceparent   string          `json:"traceparent,omitempty"`
	Job           *JobRef         `json:"job,omitempty"`
	Payload       json.RawMessage `json:"payload"`
}

type JobRef struct {
	JobID uuid.UUID `json:"job_id"`
	Fence int       `json:"fence"`
}

var (
	knownTypes = map[string]bool{"job.requested": true, "job.cancel_requested": true, "notify.requested": true,
		"job.progress": true, "job.succeeded": true, "job.failed": true}
	producerRe = regexp.MustCompile(`^(core|module:[a-z0-9][a-z0-9-]{1,39})$`)
	// MaxBody is the message size limit of core-04 §15.1.
	MaxBody = 256 << 10
)

// Parse decodes and checks the envelope rules that the consumer depends on.
func Parse(body []byte) (Envelope, error) {
	var e Envelope
	if len(body) > MaxBody {
		return e, errors.New("message body over 256 KiB")
	}
	if err := json.Unmarshal(body, &e); err != nil {
		return e, fmt.Errorf("decode envelope: %w", err)
	}
	switch {
	case e.MessageID == uuid.Nil:
		return e, errors.New("message_id is required")
	case !knownTypes[e.Type]:
		return e, fmt.Errorf("unknown type %q", e.Type)
	case e.SchemaVersion != 1:
		return e, fmt.Errorf("unsupported schema_version %d", e.SchemaVersion)
	case !producerRe.MatchString(e.Producer):
		return e, fmt.Errorf("bad producer %q", e.Producer)
	case len(e.Payload) == 0 || e.Payload[0] != '{':
		return e, errors.New("payload must be an object")
	}
	if len(e.Type) > 4 && e.Type[:4] == "job." && (e.Job == nil || e.Job.JobID == uuid.Nil || e.Job.Fence < 1 || e.ProductionID == nil) {
		return e, errors.New("job events need job.job_id, job.fence and production_id")
	}
	return e, nil
}

// OutboxMessage is one row to publish.
type OutboxMessage struct {
	Exchange   string
	RoutingKey string
	Envelope   Envelope
}

// Enqueue writes an outbox row inside the caller's business transaction (no dual write).
// The message_id is fixed here and never changes on re-publish.
func Enqueue(ctx context.Context, tx pgx.Tx, m OutboxMessage) error {
	if m.Envelope.MessageID == uuid.Nil {
		id, err := uuid.NewV7()
		if err != nil {
			return err
		}
		m.Envelope.MessageID = id
	}
	if m.Envelope.OccurredAt.IsZero() {
		m.Envelope.OccurredAt = time.Now().UTC()
	}
	m.Envelope.SchemaVersion = 1
	body, err := json.Marshal(m.Envelope)
	if err != nil {
		return err
	}
	if len(body) > MaxBody {
		return errors.New("outbox message over 256 KiB; send references, not content")
	}
	_, err = tx.Exec(ctx, `INSERT INTO outbox (message_id, exchange, routing_key, body) VALUES ($1, $2, $3, $4)`,
		m.Envelope.MessageID, m.Exchange, m.RoutingKey, body)
	return err
}
