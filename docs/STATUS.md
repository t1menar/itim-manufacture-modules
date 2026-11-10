# Manufacture — module / service status

_Last updated: 2026-11-10 (Europe/Stockholm)._

## On main

#7–#34 merged. Head includes admin-api (D24, `#25` / `31fb3ac`), the admin-panel shell (`#26` / `ab82ac0`) and the e2e verification fixes (`#34` / `5ee876d`: publish result body, review upstream, review `no_admin` fail callback, UUIDs in admin events, `video-idea.sh`).

## Accepted decisions

| # | Decision |
|---|----------|
| D18–D23 | Republish; metadata from video; admin-api was deferred (D20, **superseded in part by D24**); ideas in module-video; opaque revisions; publish intents in module-publish. |
| **D24** | **admin-api** and **admin-panel** return to scope. Order: admin-api → panel shell → screens, separate PRs. **No login.** admin-api is localhost-only (`127.0.0.1:PORT` in Compose). Host/Origin allowlist; no CORS `*`. Actor `local:admin` with env `mfa_`. Telegram bot stays review + notify only. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| #26 | Каркас admin-panel | смержен |
| #28 | Instagram и Telegram в Compose по умолчанию `real` | смержен |
| #27 | Экран **Productions** (список, детали, cancel/retry/skip) | смержен |
| #29 | Экран **Ревью и публикации** | смержен |
| #30 | Экран **Аккаунты и креды**: запись/замена секретов и аккаунтов (только «задан»/«не задан» + updated_at, без значений и длин); POST/PATCH publish accounts | смержен |
| #31 | Экран **Промпты**: шаги, версии, просмотр/diff, создание, активация, аудит | смержен |
| #32 | Экран **Журнал**: audit_log с фильтрами actor/action/outcome/from/to/cursor | смержен |
| (this) | Экран **Идеи и темы**: UI по VIDEO_ADMIN_ROUTES.md, явное состояние «module-video does not support this yet» на 404 | owner — ждать (**не мержить**) |

## Local deploy

- Entry: `./deploy/up.sh` — PG / RabbitMQ / MinIO / core / video / review / publish / **admin-api + панель**, register+activate modules, smoke.
- Панель и API: `http://127.0.0.1:58084/` (только loopback, один origin).
- Telegram and Instagram are **real** by default in Compose. For local stacks without real sends set `REVIEW_TELEGRAM_MODE=fake` and `PUBLISH_INSTAGRAM_MODE=fake`. Unset bootstrap (tests/CI) stays fake and still uses Fake clients explicitly.

## module-publish: no double posts (B6)

- `publish_ledger` (migration `0005`): one row per (intent, account). `published` → a retry returns the stored post (no API call); `publishing`/`unknown` → only reconcile (container `status_code`, recent media by caption and time), never post again; `failed` (container ERROR/EXPIRED or a definite 4xx) → may be posted by the next attempt.
- `media_publish` is never retried on 5xx/transport errors: outcome unknown → reconcile → else `status=unknown` (`publish_outcome_unknown`, core sets `needs_attention`).
- Fence right before `media_publish` (`ledger_arm`): the run must be live with the same fence, not cancelled, and at least 30 s before the job deadline. A timed-out, cancelled or superseded (higher fence for the same job) run cannot post.
- core: a retried/taken-over publish job now carries the same open `input.intents` (before it went out without intents and module-publish rejected it with 422).

## module-video

Код module-video в этом PR **не меняется**. Роуты идей/тем по-прежнему заданы в `admin-api/docs/VIDEO_ADMIN_ROUTES.md`.

Heartbeat `video-claude` иногда `down` в overview: core и admin-api здесь ни при чём (ручной `POST /internal/v1/modules/self/heartbeat` с токеном модуля даёт 200 и поднимает `health=up`; review/publish обновляют `last_seen_at` каждые ~30 с). У video фоновый цикл, судя по `last_seen_at`, не бьётся — после 90 с core честно ставит `down`. Это нужно чинить в module-video (задача не стартует или падает без лога). На стеке также бывает устаревшая регистрация `video-claude-small`.

## core: idea.ready under back-pressure (B5)

- At `scheduler.max_concurrent_productions`, `idea.ready` is no longer rolled back and retried into the DLQ: it is parked in `pending_ideas` (migration `0012`, acked, idempotent on message id and idea_ref) and started by the scheduler loop (every 2 s) when a slot frees, in priority then arrival order. A new idea never overtakes parked ones. The capacity check takes an advisory lock, so the limit cannot be overshot by a race.
- The consumer no longer sleeps before a requeue: the back-off is a timer and the default prefetch is 16, so one failing message does not hold up the others.
- module-video is unchanged: a parked idea stays `dispatched` there until core sends `idea.in_production`. Optional later: an `idea.queued` status so the video admin can show "waiting for a slot".
