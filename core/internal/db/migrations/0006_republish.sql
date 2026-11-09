-- +goose Up
-- Allow republish job mode (admin-only generation > 1).
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_mode_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_mode_check CHECK (mode IN ('create','revise','republish'));

-- Admin republish support: audit is via events; optional idempotency keys for admin POSTs.

CREATE TABLE IF NOT EXISTS idempotency_keys (
  principal text NOT NULL,
  key text NOT NULL,
  method text NOT NULL,
  path text NOT NULL,
  body_hash bytea NOT NULL,
  status_code integer NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (principal, key)
);
CREATE INDEX idempotency_keys_created_idx ON idempotency_keys (created_at);

-- +goose Down
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_mode_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_mode_check CHECK (mode IN ('create','revise'));
DROP TABLE IF EXISTS idempotency_keys;
