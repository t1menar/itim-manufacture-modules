-- +goose Up
-- D23: platform accounts + IG limits leave core; publish_intents become an orchestration
-- index (id/generation/variant/revision/status). platform_account_id is an opaque UUID
-- owned by module-publish (no FK). Denormalized platform/handle filled from module results.

ALTER TABLE publish_intents DROP CONSTRAINT IF EXISTS publish_intents_platform_account_id_fkey;
ALTER TABLE publish_intents ALTER COLUMN platform_account_id DROP NOT NULL;
ALTER TABLE publish_intents ADD COLUMN IF NOT EXISTS platform text;
ALTER TABLE publish_intents ADD COLUMN IF NOT EXISTS handle text;

DROP TABLE IF EXISTS platform_accounts;

UPDATE system_settings
SET values = values - 'instagram',
    comment = coalesce(comment, '') || ' -instagram limits → module-publish (D23)'
WHERE owner = 'core' AND is_current;

COMMENT ON TABLE publish_intents IS 'D23 orchestration index: id+generation for admin republish; domain lives in module-publish.';

-- +goose Down
CREATE TABLE IF NOT EXISTS platform_accounts (
  id uuid PRIMARY KEY,
  channel_id text NOT NULL REFERENCES channels,
  platform text NOT NULL,
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
ALTER TABLE publish_intents DROP COLUMN IF EXISTS platform;
ALTER TABLE publish_intents DROP COLUMN IF EXISTS handle;
-- platform_account_id FK not restored automatically (data-dependent)
