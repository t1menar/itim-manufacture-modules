# Target pipeline (draft for owner approval)

Status: **all five stage modules and the review module are implemented and have Manufacture SDK step adapters** (see
"Implementation status" at the end). `docs/pipeline.example.yaml` is the draft pipeline. Replaces the single
`module-video`; the old `module-video`, `module-review`, `module-publish` stay in the repo only as reference.

```
module-idea → module-scenario (research, then script) → module-review (gate 1: script)
            → module-video-generation → module-review (gate 2: finished post)
            → module-instagram-publisher → notification
```

Revision loop: a rejection at either gate returns to the stage that owns the fix (scenario for gate 1,
scenario or video-generation for gate 2) with the owner's comment, keeping the agent context.

## Modules

| Module | Reuses | Responsibility |
|---|---|---|
| `module-idea` | `module-video/ideas/` (D21) | Idea backlog, playlists, rubrics, scheduler, outcome stats. |
| `module-scenario` | steps `analysis`, `research`, `script`, `script-revise`, `post.py` | Two phases in one module: research (feasibility, verified facts, knowledge cache) and script (scene structure, script, caption and hashtags). One pinned source tree and one cache for both. |
| `module-video-generation` | `capture`, `render`, `package`, `packages/mvrender` | Capture plan and sandbox recording (real output), render, loudness, cover. |
| `module-telegram-review` | `module-review` | Telegram bot, two gates, comment-driven revisions (new core; `module-review` stays as reference). |
| `module-instagram-publisher` | `module-publish` | Reels publishing, ledger (no double posts), permalink. |

## module-idea: data model

Existing: `topics`, `ideas`, `idea_revisions`, `idea_outbox`. `topics` currently mixes "playlist" and
"sandbox environment"; split them.

- `environments` (code, sandbox image, version expectation, allowed repos) — what `topics.code` means today.
- `playlists` (id, code, title, description, status, sort_order, default_tags, default_environment).
- `playlist_ideas` (playlist_id, idea_id, position) — an idea may be in several playlists.
- `rubrics` (code: race, predict_output, break_it, myth_vs_reality, cost) with a scenario template per rubric.
- `ideas` — keep current fields and add:
  `rubric`, `key_takeaway` (one sentence), `demo_commands[]`, `expected_result`, `must_show[]`,
  `must_avoid[]`, `difficulty`, `depth` (`broad|deep`), `source_refs[]` (repo, commit, doc URL),
  `target_duration_s`, `status`, `cost_spent_usd`.
- `idea_outcomes` (idea_id, platform, views, avg_watch_s, saves, shares, follows) — to compare rubrics and
  depth by saves/follows per 1000 views (see `CONTENT.md`).

Revisions stay immutable (`idea_revisions`), the idea travels as an opaque `idea_ref`.

## Contracts between modules (artifacts, JSON Schema in each producer)

| Producer → consumer | Artifact |
|---|---|
| idea → scenario | idea document: brief, constraints, palette, instructions, environment |
| research → script (inside the module) | `research.json`: claims with source and line, pinned commit |
| scenario → review (gate 1) | `script.json`, `post.json` |
| scenario → video-generation | approved `script.json`, `post.json`, research (commit, facts) |
| video-generation → review (gate 2) | `video.mp4`, `cover.jpg`, `capture.json` (recorded output) |
| review → publisher | approved post (video, caption, tags, account) |
| any → idea | status events (`in_production|done|failed`), cost |

Numbers shown on screen come from `capture.json`, never from the model.

## module-review

- Message: video (`sendVideo`), cover, title, caption, hashtags, target account, duration, estimated cost.
- Gate 1 (script): the same card with the script text and scene list instead of a video.
- Buttons: **Approve** / **Reject**. Reject puts the card in "waiting for comment"; the next text message
  from the owner is the revision instruction. No timeout loses the request.
- Revision is applied immediately by the owning stage **with preserved context**: the stage stores its agent
  session in its own DB (session id + produced artifacts + a short running summary). On a comment it resumes that session
  instead of starting cold; if the session is gone it rebuilds from artifacts + summary, not from the whole
  transcript. Revisions are capped (`review.max_rounds`) and each round is logged with the comment.
- Approval at gate 2 creates the publish intent; the publisher posts and review sends "what was published
  where".

## Token and quality rules for all agent steps

1. Model per step in settings, not one global model: cheap model for analysis/package/schema-fix, strong
   model for script. Replace placeholder `prices.json` before relying on `usd` budgets.
2. Few-shot examples ≤ 8 KB in the target format (30–45 s, 4–5 scenes, ≤ 3 lines on screen); do not ship the
   34 KB 160 s reference or the whole 16 KB schema to every run — validate through the tool, show the agent a
   short field summary.
3. Research cache keyed by `(system, commit)`; later ideas on the same system reuse facts and only add
   idea-specific ones. Only one stage may browse the web.
4. Fail early and cheaply: deterministic validation first, then a small-model check of the hook (first 3 s)
   and of the one-sentence takeaway, then gate 1, only then capture and render.
5. Limits per stage (turns, USD, retries) lower than today; track cost per idea in `module-idea`.
6. Format limits (duration, scenes, words, terms) live in settings and validators, not in prompt text.
7. Artifact retention and inbox/outbox purge from the start (open finding 1 in `REVIEW.md`).

## Decisions after checking core v2 (see `PLATFORM_REQUIREMENTS.md`)

- Pipelines are YAML revisions in the core DB; data flows as `data` + merge patch + `$blob` claim-check.
- Agent session state is stored by the module that owns the stage (its own DB, key `(run_id, stage)`), not by the core.
  The core guarantees a stable `run_id`, `step_key` and `visit` number so a revision resumes the same session.
- The publish ledger and `unknown` handling stay in `module-instagram-publisher`; the core only needs the
  `attention` error class and `step_key` (R3, R5).
- The knowledge cache belongs to `module-scenario`; prices and cost estimates to the modules (core only sums usage).
- A review gate is a long step with a `waiting` state and `on_timeout: attention`, plus `routes` with `max_visits`.

## Open questions

- Whether capture stays an agent step (costly) or becomes a deterministic runner of `capture.plan.json`.
- Whether `module-review` stays one module with two gate types (proposed) or becomes two.
- SDK is still empty: module API names (`ctx.visit`, `ctx.step_key`, `usage`) are to be agreed with its author.

## Implementation status

| Module | Package | Platform entry (`mf-module run …`) | Real adapters in the module | Still missing |
|---|---|---|---|---|
| `module-idea` | `midea` | `midea.adapter:app` (source = scheduler, step `idea-status`) | REST API, Postgres | run lifecycle hooks (R6) instead of status steps |
| `module-scenario` | `mscenario` | `mscenario.adapter:app` | Claude Agent SDK research/script agents, git source pinning, knowledge cache | URL quote check/TTL for URL facts |
| `module-video-generation` | `mvgen` | `mvgen.adapter:app` | Claude capture planner, Docker sandbox runner (verified on postgres:17), git trees, `mvrender` | — |
| `module-telegram-review` | `mtgr` | `mtgr.adapter:app` (config `{gate: script\|post}`) | Telegram Bot API, poller, waiting step | owner registration |
| `module-instagram-publisher` | `mipub` | `mipub.adapter:app` | Graph API client, SFTP media host, ledger | account admin API; **no real Meta call has been made** |

Contract 0.3.0 (core `contract-v0.3.0`, SDK branch `s4/contract-0.3.0`) replaced the old workarounds:
- review gates park the attempt with `ctx.wait` (`step.waiting`, `waiting_human`) and finish it with `app.complete`; the
  core owns `wait.timeout`, `on_timeout: attention`, `routes` with `max_visits`;
- the revision round is `visit`; the idempotency key is `ctx.step_key` (review card, publish ledger, scenario/video results);
- the publisher calls `ctx.confirm` before `media_publish`;
- cost is reported with `ctx.add_usage` (the core sums it, `budget` is enforced by the core);
- `module-idea` follows runs through `run.started` / `run.finished` notifications (label `idea_ref`), no status steps.

Storage is MinIO (`S3_*` env): artifacts `s3://…`; the publisher gives Meta a presigned `video_url` of the public MinIO endpoint (SFTP host stays as a fallback). Rejected gate 2 returns to `scenario`: a script change re-renders; module-video-generation reuses the recorded capture
when the commands did not change, so a caption or wording fix costs no sandbox and no capture agent.

Secrets and environment per module are listed in each module's README (`MF_*` from the SDK, `<PREFIX>_*` of the module,
tokens via `secretRef`). Nothing was run against a real core, real Telegram, Meta or the Anthropic API: the code is
covered by unit tests with fakes, SDK `call_step`/`call_source`, a real Docker capture and a real ffmpeg render.
