-- +goose Up
-- Subset of core-03 §3 needed by the engine and messaging slice; remaining tables
-- (platform accounts, credentials, settings, review rounds, publications, ...) follow later.
CREATE TABLE stages (
  id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  name text NOT NULL,
  scope text NOT NULL CHECK (scope IN ('production','variant')),
  output_schema jsonb NOT NULL DEFAULT '{}',
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipelines (
  id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  name text NOT NULL,
  is_default boolean NOT NULL DEFAULT false,
  enabled boolean NOT NULL DEFAULT true,
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX pipelines_default_uq ON pipelines ((true)) WHERE is_default;

CREATE TABLE pipeline_stages (
  pipeline_id text NOT NULL REFERENCES pipelines ON DELETE CASCADE,
  position integer NOT NULL CHECK (position >= 1),
  stage_id text NOT NULL REFERENCES stages,
  timeout_s integer NOT NULL CHECK (timeout_s BETWEEN 10 AND 2592000),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
  revise_target text REFERENCES stages,
  max_rounds integer CHECK (max_rounds BETWEEN 1 AND 20),
  notify_stage text REFERENCES stages,
  PRIMARY KEY (pipeline_id, position),
  UNIQUE (pipeline_id, stage_id)
);

CREATE TABLE channels (
  id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  name text NOT NULL,
  language text NOT NULL CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  enabled boolean NOT NULL DEFAULT true,
  settings jsonb NOT NULL DEFAULT '{}',
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE routing_rules (
  id uuid PRIMARY KEY,
  language text NOT NULL,
  channel_id text NOT NULL REFERENCES channels,
  priority integer NOT NULL DEFAULT 100,
  enabled boolean NOT NULL DEFAULT true,
  UNIQUE (language, channel_id)
);

-- Minimal module registry: which module serves a stage. Registration over HTTP is a later slice.
CREATE TABLE modules (
  id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  stage_id text NOT NULL REFERENCES stages,
  enabled boolean NOT NULL DEFAULT true,
  active boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX modules_active_uq ON modules (stage_id) WHERE active;

CREATE TABLE ideas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  text text NOT NULL CHECK (length(text) BETWEEN 1 AND 2000),
  language text CHECK (language ~ '^[a-z]{2}(-[A-Z]{2})?$'),
  priority integer NOT NULL DEFAULT 0 CHECK (priority BETWEEN -100 AND 100),
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','queued','in_production','done','failed','cancelled')),
  pipeline_id text REFERENCES pipelines,
  failure jsonb,
  queued_at timestamptz,
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ideas_queue_idx ON ideas (priority DESC, queued_at, id) WHERE status = 'queued';

CREATE TABLE productions (
  id uuid PRIMARY KEY,
  idea_id bigint NOT NULL REFERENCES ideas,
  run_no integer NOT NULL CHECK (run_no >= 1),
  pipeline_id text NOT NULL REFERENCES pipelines,
  pipeline_snapshot jsonb NOT NULL,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed','cancelled')),
  language text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  rev integer NOT NULL DEFAULT 1,
  -- logical run key: one production per (idea, run number)
  UNIQUE (idea_id, run_no)
);
CREATE UNIQUE INDEX productions_live_uq ON productions (idea_id) WHERE status = 'running';

CREATE TABLE variants (
  id uuid PRIMARY KEY,
  production_id uuid NOT NULL REFERENCES productions,
  language text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','producing','in_review','revising','approved','publishing','published','skipped','failed','needs_attention','cancelled')),
  position integer NOT NULL DEFAULT 1,
  channels text[] NOT NULL DEFAULT '{}',
  attention jsonb,
  rev integer NOT NULL DEFAULT 1,
  UNIQUE (production_id, language)
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY,
  production_id uuid NOT NULL REFERENCES productions,
  variant_id uuid REFERENCES variants,
  stage_id text NOT NULL REFERENCES stages,
  module_id text REFERENCES modules,
  position integer NOT NULL,
  attempt integer NOT NULL CHECK (attempt >= 1),
  chain_id uuid NOT NULL,
  try integer NOT NULL DEFAULT 1,
  max_attempts integer NOT NULL,
  mode text NOT NULL DEFAULT 'create' CHECK (mode IN ('create','revise')),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','dispatching','dispatched','running','succeeded','failed','timed_out','cancelled')),
  -- execution ownership (core-04 §15.5); changes only on takeover, never on resend
  fence integer NOT NULL DEFAULT 1 CHECK (fence >= 1),
  timeout_s integer NOT NULL,
  request jsonb,
  output jsonb,
  error jsonb,
  progress jsonb,
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (production_id, stage_id, attempt),
  UNIQUE (chain_id, try)
);
-- C32: one live logical execution per variant across all stages, and per production for production-scope jobs.
CREATE UNIQUE INDEX jobs_variant_live_uq ON jobs (variant_id)
  WHERE variant_id IS NOT NULL AND status IN ('queued','dispatching','dispatched','running');
CREATE UNIQUE INDEX jobs_production_live_uq ON jobs (production_id)
  WHERE variant_id IS NULL AND status IN ('queued','dispatching','dispatched','running');

CREATE TABLE events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  production_id uuid,
  variant_id uuid,
  job_id uuid,
  type text NOT NULL,
  actor text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}',
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_production_idx ON events (production_id, id);

-- Transactional outbox (core-03 §3.20, core-04 §15.4)
CREATE TABLE outbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_id uuid NOT NULL UNIQUE,
  exchange text NOT NULL,
  routing_key text NOT NULL,
  body jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','dead')),
  publish_attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  locked_by text,
  locked_until timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);
CREATE INDEX outbox_pending_idx ON outbox (next_attempt_at, id) WHERE status = 'pending';

-- Consumer inbox: dedup by (consumer, message_id)
CREATE TABLE inbox (
  consumer text NOT NULL,
  message_id uuid NOT NULL,
  type text NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('applied','stale','conflict','invalid')),
  received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer, message_id)
);

-- +goose Down
DROP TABLE inbox, outbox, events, jobs, variants, productions, ideas, modules, routing_rules, channels, pipeline_stages, pipelines, stages;
