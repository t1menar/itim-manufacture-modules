# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Core stack on main

Landing: core slices through admin republish (`d2d260a`) and D19 metadata (#8).

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 / P2 / C38 | Admin-only manual republish with reason |
| D16 / C40 | Runtime prompts owned by module-video |
| **D19 / P1 / C39** | Metadata from module-video (`variants[].metadata`); no module-content |
| **D20** | **MVP excludes admin-api and admin-panel. Admin = Telegram bot (module-review) with `mfa_` + `X-Admin-Actor: tg:<id>` for allowlisted admins, plus DB access.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | D19 on main; schema+intents+limits in this PR | |
| module-video | Python | Owner through B9 on `main` | Emits metadata |
| module-review | Python | PR #6 skeleton | D20 admin commands next |
| module-publish | Python | PR #10 skeleton | Fake Instagram Login |
| module-content | — | **Rejected (D19)** | |
| admin-api / admin-panel | — | **Deferred (D20)** | |

## D20 bot admin (accepted)

module-review holds core admin token `mfa_…` (env/credentials). Admin Telegram users (allowlist) call core admin routes with `Authorization: Bearer mfa_…` and `X-Admin-Actor: tg:<telegram_user_id>`. Module `mft_` token remains for job callbacks only.
