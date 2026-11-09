-- +goose Up
ALTER TABLE publish_intents ADD COLUMN IF NOT EXISTS last_error jsonb;

-- +goose Down
ALTER TABLE publish_intents DROP COLUMN IF EXISTS last_error;
