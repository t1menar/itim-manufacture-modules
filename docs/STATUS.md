# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Core stack on main

Landing PR merged: core slices #3–#5 (through admin republish `62f133c`) via `d2d260a`.

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 / P2 / C38 | Admin-only manual republish with reason |
| D16 / C40 | Runtime prompts owned by module-video |
| D19 / P1 / C39 | Metadata from module-video (`variants[].metadata`); no module-content (**PR #8**, ready to merge) |
| **D20** | **MVP excludes admin-api and admin-panel. Admin = Telegram bot (module-review) + DB access.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | On `main` through republish; gaps closing in open PRs | Schema validation + review→intents PR; D19 snapshot on #8 |
| module-video | Python | Owner through B8 on `main` | Emits `variants[].metadata` (D19) |
| module-review | Python | PR #6 skeleton | Will grow Telegram admin later (D20) |
| module-publish | Python | Not started / skeleton PR | Fake Instagram Login only |
| module-content | — | **Rejected (D19)** | Do not implement |
| admin-api | Go | **Deferred (D20)** | Not in MVP |
| admin-panel | React | **Deferred (D13/D20)** | Not in MVP |

## Core readiness (for the owner)

Already on `main`: jobs/outbox/inbox, module registry, callbacks+fencing, settings, credentials, review revise loop, publish intents store, content revisions API, admin republish (D18).

Open (do not merge without owner):

1. **PR #8** — D19 metadata required + video→`content_revision` snapshot. Compatible with module-video `4dee415`/`3693105`. **CI green, mergeable.**
2. **Core gaps PR** — full JSON Schema validation on result → 422; review approve → generation-1 intents + publish outbox; Instagram limits in `system_settings`; D20 docs.
3. Still later: apply publish callback → intent `published`; notifications; module-publish; Telegram admin commands (D20 proposal).

### D20 proposal (not implemented): bot as admin client of core

Core already exposes admin routes behind `mfa_…` bearer (`requireAdmin`): register/activate modules, rotate tokens, module settings, **republish** (`X-Admin-Actor` stored in audit).

Suggested bot auth: module-review holds the core **admin** token (bootstrap/`mfa_`, not the module `mft_` token) in its secrets; every admin call sends `Authorization: Bearer mfa_…` and `X-Admin-Actor: tg:<telegram_user_id>` for the allow-listed Telegram admin. Module token stays for job callbacks only.

Bot commands to expose first (map 1:1 to existing core admin HTTP):

| Need | Core API | Bot |
|------|----------|-----|
| Republish with reason | `POST …/publish-intents/{id}/republish` | `/republish` + reason |
| Retry / clear `needs_attention` | (partial — may need new core admin endpoints) | `/retry`, `/skip` |
| Module activate / deactivate | `POST …/modules/{id}/activate` (+ disable if present) | `/module on\|off` |
| Rotate module token | `POST …/modules/{id}/token` | `/module token` (show once) |
| Read/put module settings | `GET/PUT …/modules/{id}/settings` | `/settings` |

DB remains escape hatch for ideas seeding, credentials insert, and anything without an admin route yet. **admin-api not planned for MVP.**

## D19 metadata note

module-video metadata shape matches `stage-video-output` / core snapshot (see PR #8). `contact_sheet`/`cover` as s3 strings are accepted by schema `oneOf` in the core-gaps PR.
