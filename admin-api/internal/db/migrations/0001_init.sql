-- +goose Up
CREATE TABLE audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  resource_type text,
  resource_id text,
  outcome text NOT NULL CHECK (outcome IN ('ok','denied','error')),
  http_status integer NOT NULL,
  problem_code text,
  request_id text,
  details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_log_at_idx ON audit_log (at DESC, id DESC);
CREATE INDEX audit_log_action_idx ON audit_log (action, at DESC);

-- +goose Down
DROP TABLE IF EXISTS audit_log;
