# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#14 merged (publish intents, P1 metadata, core gaps, module skeletons, D20 admin, publish result + notify, module-publish job intake).
#15 merged (D21 ideas-in-video spec).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Review bot = review cards + publish notifications only.** Admin ops on MVP via DB (core admin HTTP from #11 remains). `mfa_` only in env `MODULE_CORE_ADMIN_TOKEN` if/when admin client is wired; bot routing does **not** expose /republish|/module|/retry|/skip|/settings. |
| **D21** | **Ideas/topics only in module-video; statuses draft→ready→queued→dispatched→…; scheduler publishes `idea.ready` (orchestration hints only); reverse statuses via RabbitMQ; core stores only `idea_ref`; module loads idea by ref; core.`ideas` removed (no data migration); core = orchestration only** |

## Open

| PR | Content | Merge? |
|----|---------|--------|
| #16 | module-review job intake | merging |
| #17 | core/ideas-out (D21 code + D22/D23) | owner — wait |

## Still later

Core drop `ideas` + consumer `idea.ready`; module-video tables/scheduler (owner); real Telegram/Instagram; admin-api/panel; MinIO/ffprobe validation beyond structural checks.
