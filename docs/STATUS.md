# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._  
_Branch note: core slices #3–#5 are merged into the stacked intermediate branches but **not** into `main` (only #2 reached `main`). `main` also has owner-driven `module-video` B0–B4. New module work in this PR is based on `core/publish-intents` so it can talk to the full core API when the stack is landed on `main`._

## Merge state of stacked core PRs

| PR | Title | Merged into | In `main`? |
|----|-------|-------------|------------|
| #2 | foundation + PG + RabbitMQ outbox/inbox | `main` | **yes** (`cd8c27e`) |
| #3 | internal API, dispatched/timeouts, settings, review loop | `core/foundation-messaging` | **no** |
| #4 | registry, credentials, prompts helper | `core/internal-api` | **no** |
| #5 | publish intents + admin republish (D18) | `core/registry-credentials-prompts` | **no** (tip: `core/publish-intents`) |

**Action for the owner (not done by the bot):** merge the stack up into `main` in order (#3→#4→#5 / or retarget and merge the tip), resolving the divergence with `module-video` commits already on `main`. Until then, modules that need callbacks/credentials/publish intents must develop against `core/publish-intents` (or a temporary integration branch).

## Service table

| Service | Lang | Status | Depends on | Blocks / notes |
|---------|------|--------|------------|----------------|
| **core** | Go | **Partial on `main`** (foundation only); **complete through republish on `core/publish-intents`** | PG, RabbitMQ | Land #3–#5 on `main` before modules can e2e against main |
| **module-video** | Python | **In progress (owner)** B0–B4 on `main` | core, S3, Claude | Owner-owned; agents must not implement. Use fakes for contract tests only |
| **module-review** | Python | **Started (this PR)** — phase 1 skeleton | core (#3+), PG (own DB `review`), Telegram (fake in tests), MinIO later | Human-in-the-loop gate; no real Telegram |
| **module-publish** | Python | **Not started** (README stub) | core (#5 intents), Instagram Login API (fake Graph only) | After review path exists; no real Instagram posts |
| **module-content / metadata** | Python | **Not started — blocked** | P1 not accepted | Do not start until owner chooses separate `content-claude` stage vs video `metadata` object |
| **admin-api** | Go | **Not started** (README + some spec edits on `main`) | core, own DB | In MVP scope (D13) but large surface (auth/2FA/CRUD); better after core stack is on `main` |
| **admin-panel** | React/TS | **Deferred (D13)** | admin-api | Out of MVP; do not start |

## Why `module-review` next

1. Critical path after video: nothing publishes without review (overview goals).
2. Spec phase 1 is scoped (~600 lines) with clear bootstrap env and `/info`/`/health`/`/ready`.
3. Fewer open product decisions than publish (Instagram adapter) or admin-api (full IAM).
4. P1 content module is unresolved — skipped on purpose.
5. Mirrors owner’s `module-video` Python layout for consistency.

## Decisions still needed from the owner

| # | Topic | Options | Impact |
|---|-------|---------|--------|
| P1 | Who produces title/description/tags | Separate `content-claude` stage vs video optional `metadata` | Blocks module-content; publish can consume whichever shape core accepts |
| Stack | Land core #3–#5 on `main` | Merge chain / retarget tip | Unblocks e2e of review/publish against `main` |
| Review bot | Telegram bot credential in core | Create `cred:telegram-review-bot` when wiring | Needed for phase 4+ real polling (tests use fake) |

## Out of scope for agents (standing rules)

- No merge of stacked PRs without explicit ask
- No real Instagram / Telegram network calls; fake/mock clients only
- No production deploys, no secrets in git
- No force-push / amend of pushed commits / hook bypass
- Do not implement `module-video` (owner)
