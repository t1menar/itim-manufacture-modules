-- +goose Up
-- D21: ideas leave core. Productions keep opaque idea_ref (id+rev) only; no idea body.

ALTER TABLE productions ADD COLUMN IF NOT EXISTS idea_ref text;
ALTER TABLE productions ADD COLUMN IF NOT EXISTS idea_rev integer;

UPDATE productions SET idea_rev = 1 WHERE idea_rev IS NULL;
UPDATE productions SET idea_ref = 'idea:' || idea_id::text || ':v' || idea_rev::text WHERE idea_ref IS NULL;

ALTER TABLE productions ALTER COLUMN idea_ref SET NOT NULL;
ALTER TABLE productions ALTER COLUMN idea_rev SET NOT NULL;

ALTER TABLE productions DROP CONSTRAINT IF EXISTS productions_idea_rev_chk;
ALTER TABLE productions ADD CONSTRAINT productions_idea_rev_chk CHECK (idea_rev >= 1);
ALTER TABLE productions DROP CONSTRAINT IF EXISTS productions_idea_ref_chk;
ALTER TABLE productions ADD CONSTRAINT productions_idea_ref_chk CHECK (idea_ref ~ '^idea:[0-9]+:v[0-9]+$');

-- Drop FK to ideas; idea_id stays as orchestration key for live uniqueness.
ALTER TABLE productions DROP CONSTRAINT IF EXISTS productions_idea_id_fkey;

CREATE UNIQUE INDEX IF NOT EXISTS productions_idea_ref_uq ON productions (idea_ref);

DROP TABLE IF EXISTS ideas;

-- +goose Down
CREATE TABLE IF NOT EXISTS ideas (
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
CREATE INDEX IF NOT EXISTS ideas_queue_idx ON ideas (priority DESC, queued_at, id) WHERE status = 'queued';

-- Down does not restore production rows' FK or idea bodies (D21: no data migration).
ALTER TABLE productions DROP CONSTRAINT IF EXISTS productions_idea_ref_chk;
ALTER TABLE productions DROP CONSTRAINT IF EXISTS productions_idea_rev_chk;
DROP INDEX IF EXISTS productions_idea_ref_uq;
ALTER TABLE productions DROP COLUMN IF EXISTS idea_ref;
ALTER TABLE productions DROP COLUMN IF EXISTS idea_rev;
