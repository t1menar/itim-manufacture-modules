# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#21 merged (real Telegram #20, real Instagram Graph Reels #21).

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
| **D24** | **Module-owned secrets in each module DB** (`module_secrets` / `module_settings`; IG token on `platform_accounts.access_token`). Env = dev fallback only. No Core vault dependency for these. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| (this) | Module DB credentials (review + publish) | owner — wait |
| (pending) | MinIO + presigned HTTPS for `s3://` | owner — wait; reads S3 keys from module DB |

## Real integrations

- **Telegram (module-review):** done (#20). Token: `module_secrets.telegram.bot_token` (env fallback).
- **Instagram (module-publish):** done (#21). Token: `platform_accounts.access_token` (env / default secret fallback). **Blocker:** public HTTPS `video_url` until MinIO PR.

## module-video

Not touched in credentials PR. For MinIO later: same `module_secrets`/`module_settings` (`s3.*`) pattern to upload artifacts and keep `s3://manufacture/…` refs.
