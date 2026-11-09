# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#17 merged (through D21 ideas-out).

## Accepted decisions

| # | Decision |
|---|----------|
| D18 | Admin republish with reason |
| D16 | Prompts in module-video |
| D19 | Metadata from module-video |
| **D20** | **Review bot = review cards + publish notifications only.** |
| **D21** | **Ideas/topics only in module-video; `idea.ready` / reverse statuses; core stores only `idea_ref`.** |
| **D22** | **Content revisions in core are an opaque blob + sha256 (no domain field parsing as source of truth).** |
| **D23** | **Publish intents + platform accounts + IG limits live in module-publish; core keeps orchestration intent id/generation for republish.** |

## Domain carve-out plan (audit)

1. D21 — **done (#17)**.
2. D22 opaque revisions — PR #18 (do not merge until asked).
3. D23 intents → module-publish — PR #19 (do not merge until asked).
4. review_rounds detail → module-review — later.

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| #18 | D22 opaque content_revisions | owner — wait |
| #19 | D23 intents/accounts/IG limits → module-publish | owner — wait |

## module-video

No changes required for D22/D23.
