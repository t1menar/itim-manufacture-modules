# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#19 merged (through D23 intents-in-publish).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Review bot = review cards + publish notifications only.** |
| **D21** | **Ideas/topics only in module-video; `idea.ready` / reverse statuses; core stores only `idea_ref`.** |
| **D22** | **Content revisions in core are an opaque blob + sha256.** |
| **D23** | **Publish intents + platform accounts + IG limits live in module-publish.** |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| #20 | module-review real Telegram Bot API | owner — wait |
| (this) | module-publish real Instagram Graph Reels | owner — wait |

## Real integrations

- **Telegram (module-review):** `REVIEW_TELEGRAM_MODE=fake|real`, token via `REVIEW_TELEGRAM_BOT_TOKEN`.
- **Instagram (module-publish):** `PUBLISH_INSTAGRAM_MODE=fake|real`. Graph API Reels (`media_type=REELS` → poll `status_code` → `media_publish`). Token via env or Core credentials vault (`credential_ref` on account). **Blocker:** `video_url` must be public HTTPS — MinIO/presigned URLs not wired yet (`s3://` rejected with a clear error).

## module-video

Not touched.
