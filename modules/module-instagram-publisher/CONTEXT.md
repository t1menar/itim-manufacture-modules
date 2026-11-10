# module-instagram-publisher: context

- Rewrite of `module-publish` for the new pipeline: same Graph flow and safety rules (container → poll →
  `media_publish` never retried → reconcile), without legacy fence/AMQP/HTTP-callback code, direct-upload mode
  and DB-stored tokens.
- Entry point: `service.PublishService.publish(PublishRequest, confirm)`; `PublishRequest` is built from the
  approved variant of module-video-generation (`video.ref/sha256`, `cover.ref`, `post.caption/hashtags`).
- Ledger key = (account, sha256(video sha + final caption)). Same content to the same account never posts twice.
- Meta quirks (see AGENTS.md gotchas 5-6): system-user tokens need `graph.facebook.com` and `v27.0`; the caption is
  cut to 500 chars and 8 hashtags; the video must be fetched from a public https URL (SFTP web host).
- Not done: SDK adapter (`step_key`, lease `confirm`, usage), S3 loader for `SftpHost`, accounts admin API, janitor.
