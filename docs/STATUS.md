# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#16 merged (through module-publish/#14 and module-review/#16 job intake; D21 ideas-in-video spec #15).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Review bot = review cards + publish notifications only.** Admin ops on MVP via DB (core admin HTTP from #11 remains). `mfa_` only in env `MODULE_CORE_ADMIN_TOKEN` if/when admin client is wired; bot routing does **not** expose /republish|/module|/retry|/skip|/settings. |
| **D21** | **Ideas/topics only in module-video; statuses draft→ready→queued→dispatched→…; scheduler publishes `idea.ready` (orchestration hints only); reverse statuses via RabbitMQ; core stores only `idea_ref`; module loads idea by ref; core.`ideas` removed (no data migration); core = orchestration only** |
| **D22** | **Content revisions in core are an opaque blob + sha256 (no domain field parsing as source of truth)** |
| **D23** | **Publish intents live in module-publish; core keeps only id/generation for republish. Principle: core = system orchestration, no module domain** |

## Domain carve-out plan (audit)

1. D21 core ideas-out (this PR) — drop `ideas`, consumer `idea.ready`.
2. Opaque content_revisions (D22) — stop interpreting metadata keys in Go.
3. Publish intents → module-publish; core keeps intent id/generation (D23) — after #14 stable.
4. review_rounds detail → module-review — after #16.
5. Channel content settings / IG limits → modules.

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| #17 | core/ideas-out (D21 code + D22/D23) | owner — **do not merge until asked** |

## module-video owner follow-up (D21)

Job `input.idea {id,text,language}` is replaced by `input.idea_ref {id,rev}`. Module must load the idea document from its DB. No transitional dual-read of `input.idea` in core or other modules.
Still later: module-video tables/scheduler; real Telegram/Instagram; admin-api/panel; MinIO/ffprobe.
