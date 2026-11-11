# module-telegram-review

Manufacture stage `review`: the human gates of the pipeline in Telegram. Package `mtgr`, env `MTGR_*`.
Successor of `module-review` for the new pipeline (the old module stays as reference).

| Gate | Card | Next on approve | On reject |
|---|---|---|---|
| `script` (after scenario) | title, hook, takeaway, scenes with narration, caption, cost so far | module-video-generation | scenario rewrites the script only (research is reused) |
| `post` (finished post) | video, duration/size, caption, hashtags, account, cost | module-instagram-publisher | scenario (script change → re-render; capture is reused if commands are unchanged) |

```
ReviewService.open(OpenRequest)  → card with ✅ Approve / ❌ Reject
tap ✅                            → Decision(approved)
tap ❌                            → "what should be fixed?" → next text = comment → Decision(rejected, comment, round)
revised card                      → replies to the previous card, "revision N"
```

- One session per `step_key`: a retried platform step finds its card, never sends a second.
- `Decision` goes to a `DecisionSink` (the platform adapter finishes the waiting step), at-least-once and
  idempotent by `step_key`; `redeliver()` re-sends decisions the platform did not acknowledge.
- Rounds per (idea, gate) are capped (`max_rounds`); past the cap the gate `escalated`s to the operator.
- `expire_due()` turns overdue gates into `expired` (platform `on_timeout: attention`); `cancel(step_key)` for superseded runs.
- Only `owners` (user or chat ids) can decide; repeated or late taps and redelivered Telegram updates are no-ops.
- The agent context is **not** stored here. The stage that owns the fix resumes its own session with the comment
  (`Revision` in module-scenario, `Previous` in module-video-generation).
- `TelegramBot` (Bot API over httpx, video >50 MB goes as text with a note) and `FakeBot`; the token is never logged.

Platform: `adapter.py` is the Manufacture SDK step (`mf-module run mtgr.adapter:app`), one module for both gates:
the step `config` is `{gate: script|post}`, the input carries `idea_ref`, `round` (0 first visit), `scenario` or `variant`.
The step opens the card and *waits* with heartbeats (no waiting state in contract 0.2.1, requirement R1); a restarted
step finds the stored decision. Output `outcome` approved|rejected (+`comment`, `round`) for pipeline `when` routing;
escalated/expired/cancelled → `attention`. Env: `MTGR_DATABASE_URL`, `MTGR_BOT_TOKEN`, `MTGR_OWNERS` (comma-separated
Telegram ids), `MTGR_MAX_ROUNDS`, `MTGR_DEADLINE_H`. The background poller (updates, unsent cards, redelivery, deadlines) starts
with the first step.

Not done: S3 loader for the video (only `file://`), owner registration (owners come from settings).

```bash
uv sync && make check
```
