# Manufacture — module / service status

_Last updated: 2026-11-10 (Europe/Stockholm)._

## On main

#7–#24 merged earlier (deploy local stack #24, Telegram, Instagram, credentials, MinIO, heartbeats, uploads, video pipeline). Head includes commits through `d319666`.

## Accepted decisions

| # | Decision |
|---|----------|
| D18–D23 | Republish; metadata from video; admin-api was deferred (D20, **superseded in part by D24**); ideas in module-video; opaque revisions; publish intents in module-publish. |
| **D24** | **admin-api** and **admin-panel** return to scope. Order: admin-api → panel shell → screens, separate PRs. **No login.** admin-api is localhost-only (`127.0.0.1:PORT` in Compose). Host/Origin allowlist; no CORS `*`. Actor `local:admin` with env `mfa_`. Telegram bot stays review + notify only. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| (this) | `admin-api` + core/publish/review admin query routes; specs D24 | owner — wait (**do not merge**) |

## Local deploy

- Entry: `./deploy/up.sh` — PG / RabbitMQ / MinIO / core / video / review / publish / **admin-api**, register+activate modules, smoke.
- admin-api: `http://127.0.0.1:58084` (published on loopback only).
- Fake TG/IG by default.

## module-video

Application code is **not** modified in the admin-api PR. Missing ideas/topics admin routes are specified in `admin-api/docs/VIDEO_ADMIN_ROUTES.md` and proxied by admin-api.
