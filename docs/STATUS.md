# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#13 merged (publish intents, P1 metadata, core gaps, module skeletons, D20 admin, publish result + notify).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| D20 | Bot admin: `mfa_` only in env `MODULE_CORE_ADMIN_TOKEN` + `X-Admin-Actor: tg:<id>`; no admin-api in MVP |
| **D21** | **Ideas + topics owned by module-video; scheduler in module-video publishes `idea.ready` (outbox, no re-send); core keeps idea snapshot on production; core.`ideas` deprecated; MVP create via DB; bot = review only** |

## Open

| PR | Content | Merge? |
|----|---------|--------|
| #14 | module-publish job intake | owner — do not merge until asked |
| (this) ideas-in-video spec | `module-video/docs/IDEAS.md` + `contracts/{idea,topic}.json` + D21 | owner — **do not merge until green CI + review** |

## Still later

Real Telegram polling; real Instagram Login; admin-api/panel; core consumer of `idea.ready` + drop core.`ideas`; module-video ideas tables/scheduler (owner); module-video owned by owner.
