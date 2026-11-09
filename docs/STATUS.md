# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#13 merged (intents, metadata, modules, D20 admin, publish-result+notify).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Bot admin: `mfa_` only in env `MODULE_CORE_ADMIN_TOKEN` (not a Core credential ref) + `X-Admin-Actor: tg:<id>` allowlist; no admin-api in MVP** |

## Open

| PR | Content | Merge? |
|----|---------|--------|
| (A) module-publish job intake | HTTP+AMQP accept, runs+lease, Fake IG runner, callbacks | owner |
| (B) module-review job intake | review sessions, Fake Telegram cards, approve/reject | owner — after A CI |

## Still later

Real Telegram polling; real Instagram Login; admin-api/panel; MinIO/ffprobe validation beyond structural checks.
