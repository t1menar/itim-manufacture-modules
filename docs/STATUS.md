# Manufacture — module / service status

_Last updated: 2026-11-10 (Europe/Stockholm)._

## On main

#7–#26 merged. Head includes admin-api (D24, `#25` / `31fb3ac`) and the admin-panel shell (`#26` / `ab82ac0`).

## Accepted decisions

| # | Decision |
|---|----------|
| D18–D23 | Republish; metadata from video; admin-api was deferred (D20, **superseded in part by D24**); ideas in module-video; opaque revisions; publish intents in module-publish. |
| **D24** | **admin-api** and **admin-panel** return to scope. Order: admin-api → panel shell → screens, separate PRs. **No login.** admin-api is localhost-only (`127.0.0.1:PORT` in Compose). Host/Origin allowlist; no CORS `*`. Actor `local:admin` with env `mfa_`. Telegram bot stays review + notify only. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| (this) | Instagram publish в Compose по умолчанию `real`; Telegram остаётся `fake` | owner — ждать (**не мержить**) |

## Local deploy

- Entry: `./deploy/up.sh` — PG / RabbitMQ / MinIO / core / video / review / publish / **admin-api + панель**, register+activate modules, smoke.
- Панель и API: `http://127.0.0.1:58084/` (только loopback, один origin).
- Telegram: fake by default. Instagram: **real** by default in Compose (`PUBLISH_INSTAGRAM_MODE`); for local stacks without real posts set `PUBLISH_INSTAGRAM_MODE=fake`. Unset bootstrap (tests/CI) stays fake and still uses `FakeInstagramClient` explicitly.

## module-video

Код module-video в этом PR **не меняется**. Роуты идей/тем по-прежнему заданы в `admin-api/docs/VIDEO_ADMIN_ROUTES.md`.

Heartbeat `video-claude` иногда `down` в overview: core и admin-api здесь ни при чём (ручной `POST /internal/v1/modules/self/heartbeat` с токеном модуля даёт 200 и поднимает `health=up`; review/publish обновляют `last_seen_at` каждые ~30 с). У video фоновый цикл, судя по `last_seen_at`, не бьётся — после 90 с core честно ставит `down`. Это нужно чинить в module-video (задача не стартует или падает без лога). На стеке также бывает устаревшая регистрация `video-claude-small`.
