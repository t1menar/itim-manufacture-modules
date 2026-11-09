-- +goose Up
-- Content revisions and publish intents (core-03 §3.20 / core-04 §16). P2 republish stays off:
-- generation > 1 is only created by an explicit admin path that is not enabled in this slice.

CREATE TABLE platform_accounts (
  id uuid PRIMARY KEY,
  channel_id text NOT NULL REFERENCES channels,
  platform text NOT NULL CHECK (platform ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  handle text,
  external_id text,
  credential_id uuid,
  enabled boolean NOT NULL DEFAULT true,
  settings jsonb NOT NULL DEFAULT '{}',
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (channel_id, platform, handle)
);
CREATE UNIQUE INDEX platform_accounts_ext_uq ON platform_accounts (platform, external_id)
  WHERE external_id IS NOT NULL;

CREATE TABLE content_revisions (
  id uuid PRIMARY KEY,
  variant_id uuid NOT NULL REFERENCES variants ON DELETE CASCADE,
  revision integer NOT NULL CHECK (revision >= 1),
  body jsonb NOT NULL,
  sha256 bytea NOT NULL,
  source_job_id uuid NOT NULL REFERENCES jobs,
  approved_round integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (variant_id, revision)
);

CREATE TABLE publish_intents (
  id uuid PRIMARY KEY,
  variant_id uuid NOT NULL REFERENCES variants ON DELETE CASCADE,
  platform_account_id uuid NOT NULL REFERENCES platform_accounts,
  generation integer NOT NULL CHECK (generation >= 1),
  content_revision_id uuid NOT NULL REFERENCES content_revisions,
  status text NOT NULL CHECK (status IN ('pending','in_progress','published','failed','unknown','cancelled')),
  authorized_by text,
  reason text,
  job_id uuid REFERENCES jobs,
  external_post_id text,
  url text,
  published_at timestamptz,
  rev integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (variant_id, platform_account_id, generation),
  CHECK (generation = 1 OR (authorized_by IS NOT NULL AND reason IS NOT NULL AND length(trim(reason)) > 0))
);
CREATE INDEX publish_intents_status_idx ON publish_intents (status) WHERE status IN ('pending','in_progress','unknown');

-- +goose Down
DROP TABLE IF EXISTS publish_intents, content_revisions, platform_accounts;
