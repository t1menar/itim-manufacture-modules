-- +goose Up
-- Callbacks/dispatch/settings/review fields for the internal-api slice.

ALTER TABLE modules
  ADD COLUMN IF NOT EXISTS token_hash bytea,
  ADD COLUMN IF NOT EXISTS token_prefix text,
  ADD COLUMN IF NOT EXISTS prev_token_hash bytea,
  ADD COLUMN IF NOT EXISTS prev_token_expires_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS modules_token_hash_uq ON modules (token_hash) WHERE token_hash IS NOT NULL;

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS deadline timestamptz,
  ADD COLUMN IF NOT EXISTS dispatched_at timestamptz,
  ADD COLUMN IF NOT EXISTS started_at timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS round integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS settings_version integer;
CREATE INDEX IF NOT EXISTS jobs_deadline_idx ON jobs (deadline)
  WHERE status IN ('dispatched', 'running') AND deadline IS NOT NULL;

ALTER TABLE variants
  ADD COLUMN IF NOT EXISTS review_round integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_rounds integer,
  ADD COLUMN IF NOT EXISTS extra_rounds integer NOT NULL DEFAULT 0;

CREATE TABLE review_rounds (
  id uuid PRIMARY KEY,
  variant_id uuid NOT NULL REFERENCES variants ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES jobs,
  round integer NOT NULL CHECK (round >= 1),
  decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
  reason text CHECK (reason IS NULL OR reason ~ '\S'),
  reviewer jsonb NOT NULL,
  decided_at timestamptz NOT NULL,
  UNIQUE (variant_id, round)
);

-- Versioned settings for reserved owners (core, admin-api) and modules.
CREATE TABLE system_settings (
  owner text NOT NULL CHECK (owner IN ('core', 'admin-api')),
  version integer NOT NULL CHECK (version >= 1),
  values jsonb NOT NULL,
  valid boolean NOT NULL DEFAULT true,
  comment text,
  author text NOT NULL DEFAULT 'system',
  is_current boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner, version)
);
CREATE UNIQUE INDEX system_settings_current_uq ON system_settings (owner) WHERE is_current;

CREATE TABLE module_settings (
  module_id text NOT NULL REFERENCES modules ON DELETE CASCADE,
  version integer NOT NULL CHECK (version >= 1),
  values jsonb NOT NULL,
  valid boolean NOT NULL DEFAULT true,
  comment text,
  author text NOT NULL DEFAULT 'system',
  is_current boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (module_id, version)
);
CREATE UNIQUE INDEX module_settings_current_uq ON module_settings (module_id) WHERE is_current;

-- Seed core settings v1 (subset of core-04 §11 used by this slice).
INSERT INTO system_settings (owner, version, values, valid, is_current, comment)
VALUES (
  'core', 1,
  jsonb_build_object(
    'default_language', 'en',
    'scheduler', jsonb_build_object('max_concurrent_productions', 2),
    'review', jsonb_build_object('max_rounds', 3),
    'callbacks', jsonb_build_object('base_url', 'http://core:8080'),
    'modules', jsonb_build_object('token_rotation_grace_s', 900)
  ),
  true, true, 'seed'
) ON CONFLICT DO NOTHING;

-- +goose Down
DROP TABLE IF EXISTS module_settings, system_settings, review_rounds;
DROP INDEX IF EXISTS jobs_deadline_idx;
ALTER TABLE variants DROP COLUMN IF EXISTS review_round, DROP COLUMN IF EXISTS max_rounds, DROP COLUMN IF EXISTS extra_rounds;
ALTER TABLE jobs DROP COLUMN IF EXISTS deadline, DROP COLUMN IF EXISTS dispatched_at, DROP COLUMN IF EXISTS started_at,
  DROP COLUMN IF EXISTS cancel_requested, DROP COLUMN IF EXISTS round, DROP COLUMN IF EXISTS settings_version;
DROP INDEX IF EXISTS modules_token_hash_uq;
ALTER TABLE modules DROP COLUMN IF EXISTS token_hash, DROP COLUMN IF EXISTS token_prefix,
  DROP COLUMN IF EXISTS prev_token_hash, DROP COLUMN IF EXISTS prev_token_expires_at;
