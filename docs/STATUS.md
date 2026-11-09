# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#15 merged (through D21 ideas-in-video spec).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| D20 | Bot admin token `mfa_` in `MODULE_CORE_ADMIN_TOKEN` + `X-Admin-Actor: tg:<id>`; no admin-api in MVP |
| D21 | Ideas/topics only in module-video; `idea.ready` / reverse statuses over RabbitMQ; core stores only `idea_ref` |
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
| #14 | module-publish job intake | owner — wait (touches publish job input / intents) |
| #16 | module-review job intake | owner — wait |
| (this) core/ideas-out | D21 implementation | owner — **do not merge until asked** |

## module-video owner follow-up (D21)

Job `input.idea {id,text,language}` is replaced by `input.idea_ref {id,rev}`. Module must load the idea document from its DB. Transitional dual-read is optional and not implemented in core.
