-- +goose Up
-- Module registry fields, credentials vault, prompt versions (MVP store in core; D16 places
-- prompts in the module DB — see README).

ALTER TABLE modules
  ADD COLUMN IF NOT EXISTS name text,
  ADD COLUMN IF NOT EXISTS endpoint text,
  ADD COLUMN IF NOT EXISTS version text,
  ADD COLUMN IF NOT EXISTS contract integer,
  ADD COLUMN IF NOT EXISTS info jsonb,
  ADD COLUMN IF NOT EXISTS settings_schema jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS admin_endpoints text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS token_ciphertext bytea,
  ADD COLUMN IF NOT EXISTS token_nonce bytea,
  ADD COLUMN IF NOT EXISTS token_key_version integer,
  ADD COLUMN IF NOT EXISTS health text NOT NULL DEFAULT 'unknown'
    CHECK (health IN ('unknown','up','degraded','down','unauthorized')),
  ADD COLUMN IF NOT EXISTS health_detail jsonb,
  ADD COLUMN IF NOT EXISTS consecutive_failures integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_health_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_seen_at timestamptz,
  ADD COLUMN IF NOT EXISTS info_refreshed_at timestamptz,
  ADD COLUMN IF NOT EXISTS rev integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- Fill name/endpoint for seed modules used by earlier tests.
UPDATE modules SET name = coalesce(name, id), endpoint = coalesce(endpoint, 'http://127.0.0.1:9/' || id)
  WHERE name IS NULL OR endpoint IS NULL;
ALTER TABLE modules ALTER COLUMN name SET NOT NULL;
ALTER TABLE modules ALTER COLUMN endpoint SET NOT NULL;

CREATE TABLE credentials (
  id uuid PRIMARY KEY,
  ref text NOT NULL UNIQUE CHECK (ref ~ '^cred:[a-z0-9][a-z0-9-]{1,59}$'),
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('api_key','oauth_token','bot_token','password','s3_keys','generic')),
  access text NOT NULL DEFAULT 'job' CHECK (access IN ('job','module')),
  allowed_modules text[] NOT NULL DEFAULT '{}',
  owner_module text,
  ciphertext bytea NOT NULL,
  nonce bytea NOT NULL CHECK (length(nonce) = 12),
  key_version integer NOT NULL,
  last4 text NOT NULL,
  expires_at timestamptz,
  rotated_at timestamptz,
  last_used_at timestamptz,
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE credential_access_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  credential_id uuid NOT NULL REFERENCES credentials ON DELETE CASCADE,
  principal text NOT NULL,
  job_id uuid,
  action text NOT NULL CHECK (action IN ('read','write')),
  outcome text NOT NULL CHECK (outcome IN ('allowed','denied')),
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX credential_access_log_cred_idx ON credential_access_log (credential_id, at DESC);

-- Prompt versions: immutable rows; at most one active per (owner_module, prompt_id).
-- Spec D16 places this in the module DB; core holds an MVP copy so jobs can snapshot prompts
-- before the video module exists.
CREATE TABLE prompts (
  owner_module text NOT NULL,
  prompt_id text NOT NULL CHECK (prompt_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  version integer NOT NULL CHECK (version >= 1),
  body text NOT NULL,
  variables text[] NOT NULL DEFAULT '{}',
  sha256 bytea NOT NULL,
  active boolean NOT NULL DEFAULT false,
  author text NOT NULL DEFAULT 'system',
  comment text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_module, prompt_id, version)
);
CREATE UNIQUE INDEX prompts_active_uq ON prompts (owner_module, prompt_id) WHERE active;

-- Seed health.offline_after_s into core settings via a new version is done in code/tests;
-- keep seed v1 compatible. Dispatcher reads health.offline_after_s with default 90.

-- +goose Down
DROP TABLE IF EXISTS prompts, credential_access_log, credentials;
ALTER TABLE modules
  DROP COLUMN IF EXISTS name, DROP COLUMN IF EXISTS endpoint, DROP COLUMN IF EXISTS version,
  DROP COLUMN IF EXISTS contract, DROP COLUMN IF EXISTS info, DROP COLUMN IF EXISTS settings_schema,
  DROP COLUMN IF EXISTS admin_endpoints, DROP COLUMN IF EXISTS token_ciphertext,
  DROP COLUMN IF EXISTS token_nonce, DROP COLUMN IF EXISTS token_key_version,
  DROP COLUMN IF EXISTS health, DROP COLUMN IF EXISTS health_detail,
  DROP COLUMN IF EXISTS consecutive_failures, DROP COLUMN IF EXISTS last_health_at,
  DROP COLUMN IF EXISTS last_seen_at, DROP COLUMN IF EXISTS info_refreshed_at,
  DROP COLUMN IF EXISTS rev, DROP COLUMN IF EXISTS updated_at;
