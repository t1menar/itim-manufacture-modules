# module-video — context for agents

Python 3.12 / FastAPI / SQLAlchemy+asyncpg / aio-pika / S3 (MinIO) / Claude Agent SDK / ffmpeg. Module id `video-claude`.
Owns the **ideas backlog** (D21), the video pipeline and prompts. Read `README.md` for API/config tables and `docs/IDEAS.md` for the ideas model.

## Layout
- `src/mvideo/` service: `app.py` (FastAPI wiring), `intake.py` (`POST /v1/jobs`, idempotent on job_id), `service.py`, `core_client.py`
  (callbacks with `X-Fence`), `settings_model.py` (settings schema + `DEFAULT_PALETTE`), `brand.py` (per-topic brand palettes), `post.py`
  (caption/hashtags), `revise.py`, `credential_gateway.py`, `heartbeat.py`, `cli.py` (`mvideo`, `agent-smoke`).
  - `pipeline/` — `runner.py` (leases, resume, step cache, cancel), `worker.py`, `real.py` (real pipeline definition), `budget.py`,
    `steps/{analysis,agent_step,media_steps,fake}.py` (analysis/research/script/capture/render/package/script-revise).
  - `agents/` Claude Agent SDK containers (`video-agent` image, egress proxy allowlist), `sandbox/` throwaway capture containers
    (digest-pinned images, network none), `sources/` git checkouts of reference sources, `validate/` schema + rule checks,
    `ideas/` (scheduler, outbox relay, status consumer, vendored schemas), `db/migrations` (Alembic), `observability/`, `net/`.
- `src/mvrender/` standalone renderer (must not import `mvideo`; import-linter enforces): `scenario.py`/`timeline.py`/`timing.py` build the
  timeline, `frame.py` + `draw/*` render frames as a pure function of time (terminal, debugger, diagram, captions, syntax highlighting),
  `encode.py` parallel chunk encoding (process pool; `_init_worker` receives fonts, settings, fps, `reading_wps`), `sfx.py` synthesised
  effects, `package.py` (`mux_final`, loudness loop, cover, checks), `safezone.py`, `sheet.py` contact sheet, `palette.py`.
- `prompts/<step>/<ver>/{CLAUDE.md,task.md}` seed prompts (DB is the source at runtime: `prompt_versions`, `prompt_active`, `prompt_audit`; never edit versions, add new ones).
- `agent/` agent image; `reference/create_database/` reference scenario; `fonts/` Inter + JetBrains Mono.

## Pipeline semantics
`analysis → research → script → capture → render → package → result`. Revise mode (`script-revise`, capture reused unless commands changed,
post text reused unless hook/first captions changed). Numbers shown on screen come from the recorded sandbox output, never from the model.
Step cache key = hash(step name+version, model, `settings_keys` subset, input, idea doc, upstream sha256, prompt versions) — see AGENTS.md gotcha 1.
Limits per job (settings): `limits.job_budget_usd`, `max_jobs_per_day`, `max_agent_runs_per_hour`, `fix_rounds`, `schema_retries`;
`cost_mode` `usd` enforces budget, `estimate` (subscription) only reports.

## Ideas / scheduler
Tables `topics`, `ideas`, `idea_revisions`, `idea_outbox`, `amqp_inbox`. Scheduler tick (`VIDEO_IDEAS_TICK_S`) dispatches `queued` ideas of active
topics by priority; caps `VIDEO_IDEAS_MAX_DISPATCH`, `VIDEO_IDEAS_MAX_IN_FLIGHT`, `VIDEO_IDEAS_INTERVAL_S` (one idea per interval), `VIDEO_IDEAS_PAUSED`.
Relay publishes `idea.ready`; consumer `module.video.idea-status` handles `idea.in_production|done|failed` monotonically. Parked ideas in core stay `dispatched` here.
Topics have `code` (`postgres_internals`, `kafka_internals`) mapping to sandbox environments (`postgres17`, `kafka44`) described by `deploy/scripts/video-prepare.sh`.

## Render facts that bit us
- Loudness −16 LUFS closed loop in `package.mux_final` (see AGENTS.md); parallel workers need `reading_wps`; `RenderStep.version="2"`.
- New palette token ⇒ add to `mvrender/palette.py DEFAULTS` **and** `settings_model.DEFAULT_PALETTE`; do not make the script step depend on the palette.
- Approved frames: `tests/approved/`, regenerate with `UPDATE_APPROVED=1 uv run pytest tests/test_render.py` after intended visual changes.

## Commands
```bash
cd module-video && uv sync && make check        # ruff, mypy (strict for mvrender), lint-imports, pytest
uv run pytest -m docker                         # needs Docker (postgres:17, rabbitmq:4-management)
uv run mvideo agent-smoke --image video-agent:dev
MVIDEO_PIPELINE= (empty) uses fake steps; MVIDEO_PIPELINE=real uses Claude
```
Local venv for quick checks: `module-video/.venv/bin/{python,ruff}`. Local deploy helpers: `deploy/scripts/video-prepare.sh|video-credential.sh|video-idea.sh`.
Credential for Claude lives in table `credentials` (write-only API `/admin/v1/credentials`); never read its value.

## Not done
Real-Claude golden revise runs, `/admin/v1/runs|golden`, artifact janitor, `uv lock` refresh, real prices in `agent/prices.json`.
