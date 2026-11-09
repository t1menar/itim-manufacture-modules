# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## On main

#7–#19 merged (through D23 intents-in-publish).

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
2. D22 opaque revisions — **done (#18)**.
3. D23 intents → module-publish — **done (#19)**.
4. review_rounds detail → module-review — later.

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| (this) | module-review real Telegram Bot API | owner — wait |

## Real integrations

- **module-review Telegram:** `REVIEW_TELEGRAM_MODE=fake|real`. Real uses long-poll `getUpdates` (offset in `bot_state`, idempotent `telegram_updates_seen`). Token only via `REVIEW_TELEGRAM_BOT_TOKEN` (never logged).
- **module-publish Instagram:** see sibling PR (Graph API Reels).

## module-video

Not touched by real Telegram / Instagram work.
