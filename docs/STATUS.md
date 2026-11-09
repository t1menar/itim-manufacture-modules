# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#12 merged (publish intents, P1 metadata, core gaps, module skeletons, D20 admin deactivate/retry/skip, review admin client).

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
| (this) publish result + notify | core: publications → intents + aggregate + notify outbox; module-publish fake runner; module-review notify + FakeTelegram | owner — **do not merge until green CI + review** |

## Still later

Real Telegram polling; real Instagram Login; admin-api/panel; module-video owned by owner.
