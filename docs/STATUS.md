# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7 publish-intents, #8 D19, #9 schema+intents+limits, #10 module-publish skeleton, #6 module-review skeleton. `__pycache__` cleaned; root `.gitignore` ignores Python caches.

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 | Admin-only republish with reason |
| D16 | Runtime prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **No admin-api/panel in MVP. Bot uses `mfa_` + `X-Admin-Actor: tg:<id>` (allowlist) + DB.** |

## Open PRs (this workstream)

| PR | Content | Merge? |
|----|---------|--------|
| core admin attention | deactivate module; variant retry/skip | owner |
| module-review admin bot | CoreAdminClient + commands + fake Telegram | owner |
