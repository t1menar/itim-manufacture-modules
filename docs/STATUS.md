# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Core stack on main

Landed: #7 publish-intents, #8 D19 metadata, #9 schema+intents+limits+D20, #10 module-publish skeleton. `__pycache__` removed from `module-review/` on main; root `.gitignore` ignores Python caches.

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 / P2 / C38 | Admin-only manual republish with reason |
| D16 / C40 | Runtime prompts owned by module-video |
| **D19 / P1 / C39** | Metadata from module-video; no module-content |
| **D20** | **MVP excludes admin-api/admin-panel. Admin = Telegram bot with `mfa_` + `X-Admin-Actor: tg:<id>` (allowlist) + DB.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | On `main` through #9 | Publish outcome apply still open |
| module-video | Python | Owner B9 on `main` | Emits metadata |
| module-review | Python | This PR skeleton | D20 admin commands next |
| module-publish | Python | On `main` (#10) | Fake Instagram Login |
| module-content | — | **Rejected (D19)** | |
| admin-api / admin-panel | — | **Deferred (D20)** | |

## D20 bot admin (accepted)

module-review stores core admin token `mfa_…`. Allowlisted Telegram admins call core admin HTTP with `Authorization: Bearer mfa_…` and `X-Admin-Actor: tg:<telegram_user_id>`. Module `mft_` for job callbacks only.
