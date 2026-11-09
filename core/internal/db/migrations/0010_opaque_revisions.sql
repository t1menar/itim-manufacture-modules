-- +goose Up
-- D22: content_revisions.body is an opaque module blob; core stores sha256 and does not
-- treat metadata/video/post keys as its domain model (stage output still schema-validated).
COMMENT ON COLUMN content_revisions.body IS 'Opaque JSON blob from the producing module (D22); core does not interpret domain fields.';
COMMENT ON COLUMN content_revisions.sha256 IS 'SHA-256 of body bytes at insert time (immutable content fingerprint).';
ALTER TABLE content_revisions DROP CONSTRAINT IF EXISTS content_revisions_sha256_len;
ALTER TABLE content_revisions ADD CONSTRAINT content_revisions_sha256_len CHECK (octet_length(sha256) = 32);

-- +goose Down
ALTER TABLE content_revisions DROP CONSTRAINT IF EXISTS content_revisions_sha256_len;
COMMENT ON COLUMN content_revisions.body IS NULL;
COMMENT ON COLUMN content_revisions.sha256 IS NULL;
