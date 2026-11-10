-- +goose Up
-- B5: idea.ready that arrives while core is at max_concurrent_productions is parked here
-- (durably, acked) instead of being retried into the DLQ. The scheduler starts parked ideas
-- in priority/arrival order as soon as a production slot frees up.
CREATE TABLE pending_ideas (
  idea_ref text PRIMARY KEY,
  idea_id bigint NOT NULL,
  idea_rev integer NOT NULL,
  message_id uuid NOT NULL UNIQUE,
  payload jsonb NOT NULL,
  priority integer NOT NULL DEFAULT 0,
  attempts integer NOT NULL DEFAULT 0,
  last_error text,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pending_ideas_order_idx ON pending_ideas (priority DESC, received_at, idea_ref);

-- +goose Down
DROP TABLE pending_ideas;
