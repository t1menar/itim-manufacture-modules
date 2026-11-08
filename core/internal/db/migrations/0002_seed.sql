-- +goose Up
INSERT INTO stages (id, name, scope) VALUES
  ('video', 'Video', 'production'), ('review', 'Review', 'variant'), ('publish', 'Publish', 'variant')
ON CONFLICT DO NOTHING;
INSERT INTO pipelines (id, name, is_default) VALUES ('default-v1', 'Default', true) ON CONFLICT DO NOTHING;
INSERT INTO pipeline_stages (pipeline_id, position, stage_id, timeout_s, max_attempts, revise_target, notify_stage) VALUES
  ('default-v1', 1, 'video', 5400, 2, NULL, NULL),
  ('default-v1', 2, 'review', 604800, 1, 'video', NULL),
  ('default-v1', 3, 'publish', 1800, 3, NULL, 'review')
ON CONFLICT DO NOTHING;
INSERT INTO channels (id, name, language) VALUES ('itim', 'iTim', 'en') ON CONFLICT DO NOTHING;
INSERT INTO routing_rules (id, language, channel_id) VALUES ('00000000-0000-7000-8000-000000000001', 'en', 'itim') ON CONFLICT DO NOTHING;

-- +goose Down
DELETE FROM routing_rules; DELETE FROM channels; DELETE FROM pipeline_stages; DELETE FROM pipelines; DELETE FROM stages;
