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
| **D24** | **Module-owned secrets in each module DB** (plaintext OK for local). Env = dev fallback only. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| #22 | Module DB credentials | owner — wait |
| #23 | MinIO + `mf-storage` + public presigned GET | owner — wait (**do not merge**); stacked on #22 |

## Storage

- Default local stack: `deploy/compose.minio.yml` → `http://127.0.0.1:59000` (no domain/TLS infra).
- `S3_PUBLIC_ENDPOINT` configurable; for live Instagram from a laptop use a temporary **cloudflared/ngrok** tunnel to MinIO and set that host as public endpoint.
- Keys: module DB `s3.*` (#22); env fallback for local/CI.
- Wired: publish (IG `video_url`), review (Telegram `sendVideo`).
- **module-video not modified** — must upload into the same `s3://manufacture/…` layout.

## Real integrations

- **Telegram:** #20 + DB secrets (#22).
- **Instagram:** #21 + DB tokens (#22). Needs reachable HTTPS URL for Graph (tunnel + this MinIO PR).
