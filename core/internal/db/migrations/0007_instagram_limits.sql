-- +goose Up
-- Instagram caption/hashtag limits as system_settings (adapter defaults; verify against current docs).
UPDATE system_settings
SET values = values || jsonb_build_object(
  'instagram', jsonb_build_object(
    'max_caption_chars', 2200,
    'max_hashtags', 30,
    'caption_hashtag_separator', '\n\n'
  )
),
comment = coalesce(comment, '') || ' +instagram limits'
WHERE owner = 'core' AND is_current;

-- +goose Down
UPDATE system_settings
SET values = values - 'instagram'
WHERE owner = 'core' AND is_current;
