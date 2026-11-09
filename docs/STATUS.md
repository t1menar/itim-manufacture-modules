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
| **D24** | **Module-owned secrets in each module DB** (`module_secrets` / `module_settings`; IG token on `platform_accounts.access_token`). Env = dev fallback only. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| #22 | Module DB credentials | owner — wait |
| (this) | MinIO + `mf-storage` + public presigned GET | owner — wait (**do not merge**) |

## Storage

- Package `packages/mf-storage`: parse `s3://manufacture/…`, put/get/stat, **presign GET** with separate internal vs **public** endpoint (SigV4 host).
- Keys/endpoints: **module DB** (`s3.access_key` / `s3.secret_key` + `module_settings.s3`); env fallback for local/CI.
- Local: `deploy/compose.minio.yml`, `deploy/scripts/mfinfra-minio.sh` (docker or `/tmp/mfinfra` binary). Ports **59000/59001**.
- Wired: module-publish (Instagram `video_url`), module-review (Telegram `sendVideo` URL).
- **module-video not modified** — still emits `s3://` refs; must upload objects into the same bucket/key layout before review/publish can presign.

## Real integrations

- **Telegram:** #20 + DB secrets (#22).
- **Instagram:** #21 + DB tokens (#22). Needs public HTTPS (this MinIO PR).

## Ops still needed from user

- Public MinIO hostname + TLS reverse proxy (`S3_PUBLIC_ENDPOINT` / `module_settings.s3.public_endpoint`).
- Insert S3 keys into each module DB (see README SQL templates in #22).
