# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#17 merged (through D21 ideas-out: core drops `ideas`, `idea.ready` intake, module-video owns ideas).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Review bot = review cards + publish notifications only.** Admin ops on MVP via DB (core admin HTTP from #11 remains). `mfa_` only in env `MODULE_CORE_ADMIN_TOKEN` if/when admin client is wired; bot routing does **not** expose /republish|/module|/retry|/skip|/settings. |
| **D21** | **Ideas/topics only in module-video; statuses draft→ready→queued→dispatched→…; scheduler publishes `idea.ready` (orchestration hints only); reverse statuses via RabbitMQ; core stores only `idea_ref`; module loads idea by ref; core.`ideas` removed (no data migration); core = orchestration only** |
| **D22** | **Content revisions in core are an opaque blob + sha256 (no domain field parsing as source of truth). Stage output still JSON-Schema validated.** |
| **D23** | **Publish intents live in module-publish; core keeps only id/generation for republish. Principle: core = system orchestration, no module domain** |

## Domain carve-out plan (audit)

1. D21 core ideas-out — **done (#17)**.
2. Opaque content_revisions (D22) — this PR.
3. Publish intents → module-publish; core keeps intent id/generation (D23) — follow-up PR.
4. review_rounds detail → module-review — later.
5. Channel content settings / IG limits → modules — with D23.

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| (this) core/d22-opaque-revisions | D22 opaque content_revisions | owner — **do not merge until asked** |

## module-video

D21 follow-up is on main. For D22 no module-video code changes are required: the revision blob remains a variant-shaped JSON object (plus `variant_id`/`job_id`); consumers that read `video`/`metadata` keep working. Schema validation of the video stage result stays in core.
