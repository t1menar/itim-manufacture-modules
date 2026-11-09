# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#10, #6, #11 (admin deactivate/retry/skip). Next: #12 review admin client; then publish-result + notify.

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
| #12 module-review admin | CoreAdminClient + commands + FakeTelegram | after CI |
| (next) publish result + notify | core intents from publish callback; outbox notify; modules | owner |

## Still later

Real Telegram polling; real Instagram; admin-api/panel.
