# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 | Admin-only manual republish with reason |
| D16 | Runtime prompts owned by module-video |
| D19 | Metadata from module-video (PR #8) |
| **D20** | **MVP excludes admin-api and admin-panel. Admin = Telegram bot (module-review) + DB.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | main + open PRs #8 #9 | Schema validation + review→intents in #9 |
| module-video | Python | B9 on main | Emits metadata |
| module-review | Python | PR #6 skeleton | D20 admin bot later |
| module-publish | Python | This PR skeleton | Fake Instagram Login only |
| admin-api / admin-panel | — | **Deferred (D20)** | |

See core gaps PR for the D20 bot-as-admin proposal.
