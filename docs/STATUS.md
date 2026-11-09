# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#13 merged.

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Review bot = review cards + publish notifications only.** Admin ops on MVP via DB (core admin HTTP from #11 remains). `mfa_` only in env `MODULE_CORE_ADMIN_TOKEN` if/when admin client is wired; bot routing does **not** expose /republish|/module|/retry|/skip|/settings. |

## Open

| PR | Content | Merge? |
|----|---------|--------|
| #14 module-publish job intake | lease worker, Fake IG, callbacks | owner |
| (B) module-review job intake | video card + approve/reject+reason, revise reply chain, publish notify reply | owner — **do not merge** |

## Still later

Real Telegram/Instagram; MinIO/ffprobe; admin-api/panel; ideas in module-video (pending decision).
