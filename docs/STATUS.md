# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Core stack on main

Landed: publish-intents stack (#7), D19 metadata (#8), schema validation + review→intents + Instagram limits + D20 docs (#9).

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 / P2 / C38 | Admin-only manual republish with reason |
| D16 / C40 | Runtime prompts owned by module-video |
| **D19 / P1 / C39** | Metadata from module-video; no module-content |
| **D20** | **MVP excludes admin-api/admin-panel. Admin = Telegram bot (module-review) with `mfa_` + `X-Admin-Actor: tg:<id>` (allowlist) + DB.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | On `main` through #9 | Publish callback→intent still open |
| module-video | Python | Owner B9 on `main` | Emits metadata |
| module-review | Python | PR #6 skeleton (merging next) | D20 admin commands next |
| module-publish | Python | This PR skeleton | Fake Instagram Login only |
| module-content | — | **Rejected (D19)** | |
| admin-api / admin-panel | — | **Deferred (D20)** | |

## D20 bot admin (accepted)

module-review stores core admin token `mfa_…` (bootstrap env / credentials). Allowlisted Telegram admins: `Authorization: Bearer mfa_…` + `X-Admin-Actor: tg:<telegram_user_id>`. Module `mft_` for job callbacks only.
