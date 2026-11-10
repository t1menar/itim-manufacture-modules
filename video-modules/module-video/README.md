# module-video

Stage `video` of Manufacture: takes an idea and produces a finished English short video (1080×1920, H.264, with sound effects, cover, caption and metadata) for Instagram. Python 3.12, FastAPI, PostgreSQL, S3 (MinIO), RabbitMQ.

Specification: `../../docs/module-video/` (`module-video-01-description` … `-06-prompts`). Ideas backlog and scheduler: [`docs/IDEAS.md`](docs/IDEAS.md).

## How it works

```
idea ─► analysis ─► research ─► script ─► capture ─► render ─► package ─► result (to core)
         Claude      Claude      Claude   Claude      code       Claude+code
                                           + sandbox
```

- **Claude steps** (analysis, research, script, capture plan, package hook) run the Claude Agent SDK inside the `video-agent` container. It has no network except an egress proxy (CONNECT 443, per-step allowlist), no secrets except the one Claude credential of the job, and files only in its own workspace volumes.
- **Capture** executes the agent's plan in a throwaway sandbox container (database image pinned by digest, network none, read-only root, no binds) and records real output. Numbers on screen come from this record, never from the model.
- **Render and package** are plain code (`mvrender`): frames are a pure function of time, chunks are encoded in parallel, sound effects are synthesised, loudness is leveled to -14 LUFS, then the video is muxed, a cover is extracted, and the checks run (format, loudness, size, glyphs, safe zone, post limits).
- **Revise** (`mode: revise`) re-writes only what review asked to change and reuses the capture and the post when nothing they depend on changed.
- A step is cached by the hash of its inputs, settings and prompt versions, so a retry or a revise does not redo finished work. Runs survive a restart (leases, resume).
- The result carries `variants[0]` with the video (`s3://` ref, sha256, size, duration), contact sheet, cover, post, metadata, checks, provenance and, for revise, a `changes` text. Cost and tokens go in `metrics`.

## Run with Docker Compose

```bash
cd module-video
cp .env.example .env                                  # defaults work for a local run
docker compose --profile build build video-agent      # once: the agent image (about 1.4 GB)
docker compose up -d --build                          # module, PostgreSQL 17, RabbitMQ, MinIO
curl localhost:8080/health ; curl localhost:8080/ready
```

| Service | Port on the host | Purpose |
|---|---|---|
| module-video | 8080 | the API below |
| postgres | 55432 (`video` / `video`) | module database; manage the `credentials` table here |
| rabbitmq | 55672, UI 55673 | idea events (`MODULE_AMQP_URL`) |
| minio | 59000, console 59001 | artifacts, bucket `manufacture` |

Things to know before the first real job:

1. **Claude credential.** Insert it into the `credentials` table (see below). Without it `/ready` reports `auth: missing` and jobs block with `agent_auth_failed`.
2. **Agent image by digest.** Job settings must name `agent.image` as `repo@sha256:…`. A local image has no digest until it passes through a registry:
   `docker compose --profile registry up -d registry`, then `docker tag video-agent:dev localhost:5000/video-agent:dev && docker push localhost:5000/video-agent:dev`; use the digest from the push output. Sandbox images (for example `postgres:17`) must be pinned by digest in the same way.
3. **Docker socket.** The module starts sandbox and agent containers through `/var/run/docker.sock`; set `DOCKER_GID` to the socket's group (`0` on Docker Desktop).
4. **Core.** `MODULE_CORE_URL` and `MODULE_CORE_TOKEN` point at the core; the same token is the bearer token callers must send to this module. Without a core the module still starts, but results and progress cannot be delivered.
5. `MVIDEO_PIPELINE=` (empty) switches to fake steps that write small placeholder files: a quick check that the plumbing works, with no Claude, Docker or ffmpeg involved.

Without Compose: `uv sync`, set the variables below, `uv run mvideo`.

## Configuration

The environment holds only bootstrap values; all other settings arrive with each job (settings snapshot, schema in `/info`).

| Variable | Required | Meaning |
|---|---|---|
| `VIDEO_DATABASE_URL` | yes | `postgresql+asyncpg://…`; migrations run at start-up under an advisory lock |
| `VIDEO_LISTEN_ADDR` | yes | `host:port` |
| `MODULE_CORE_URL`, `MODULE_CORE_TOKEN` | yes | core base URL; bearer token (in and out) |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | yes | artifact storage |
| `DOCKER_HOST` | yes | Docker daemon for sandbox and agent containers |
| `VIDEO_AGENT_NETWORK` | yes | network of the agent containers (the module must be on it) |
| `MODULE_AMQP_URL`, `MODULE_AMQP_PREFIX` | no | RabbitMQ for ideas; without the URL the scheduler, relay and consumer are off |
| `VIDEO_IDEAS_TICK_S`, `VIDEO_IDEAS_MAX_DISPATCH`, `VIDEO_IDEAS_MAX_IN_FLIGHT`, `VIDEO_IDEAS_PAUSED`, `VIDEO_IDEAS_INTERVAL_S` | no | idea scheduler (defaults 5, 5, 3, off, 0). With `VIDEO_IDEAS_INTERVAL_S` > 0 one queued idea is dispatched per interval, the rest wait in `queued` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | trace export (needs the OpenTelemetry SDK, declared in `pyproject.toml`) |
| `MVIDEO_PIPELINE` | no | `real` for the Claude pipeline; anything else uses fake steps |
| `MVIDEO_SELF_HOST`, `MVIDEO_GIT_IMAGE`, `MVIDEO_AGENT_NETWORK` | no | how agents reach the module, helper image for git checkouts, agent network name |
| `FFMPEG`, `MVRENDER_FONTS` | no | ffmpeg binary (the image sets it), fonts directory |

## API

| Endpoint | Purpose |
|---|---|
| `GET /info`, `/health`, `/ready`, `/metrics` | schemas of input, output and settings; liveness; readiness (database, S3, Claude auth state); Prometheus |
| `POST /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel` | job intake (idempotent on `job_id`), status, cancel |
| `/admin/v1/prompts` | editable runtime prompts, see below |
| `/admin/v1/credentials` | write-only credential store, see below |

All except `/health`, `/ready`, `/metrics` and `/info` need `Authorization: Bearer <MODULE_CORE_TOKEN>`. Errors are `application/problem+json`.

A job refers to an idea of this module (`input.idea_ref {id, rev}`); the document is loaded from the module database. Limits per job come from settings: `limits.job_budget_usd`, `max_jobs_per_day` (6), `max_agent_runs_per_hour` (12), `fix_rounds`, `schema_retries`. Exceeding a daily or hourly limit fails the job `transient` with `retry_after`; in `usd` cost mode the job budget is enforced before each agent run (`budget_exceeded`), in `estimate` mode (subscription) it is only reported (`metrics.cost_estimated`).

## Observability

`/metrics` exposes every metric of the spec (`video_jobs_total`, `video_step_duration_seconds`, `video_cost_usd_total`, `video_tokens_total`, render, check and HTTP metrics, gauges for running and queued jobs, jobs today and agent runs in the last hour). `production_id` is never a label. Logs are JSON lines (`ts`, `level`, `service`, `production_id`, `job_id`, `run_id`, `step`, `trace_id`, `span_id`); keys such as `token`, `key`, `oauth`, `authorization` and the exact value of the Claude credential are masked. Spans: `video.job` (continues the core's `traceparent`), `step.<name>`, `agent.run`, `sandbox.exec`, `render.chunk`, `s3.upload`, `core.callback`.

## Credentials in the module database

For a local deployment the Claude credential lives in this module's database (table `credentials`, migration 0005). The module looks there first and asks the core only when the ref is not stored. Values are kept as plain text, so use this only on a machine you own. The API never returns a value, and the logs and `repr` never show it.

```bash
curl -X PUT localhost:8080/admin/v1/credentials/CLAUDE_OAUTH_TOKEN \
  -H "Authorization: Bearer $MODULE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"claude_oauth_token","value":"'"$TOKEN"'","note":"local"}'   # 201 new, 204 replaced
curl localhost:8080/admin/v1/credentials -H "Authorization: Bearer $MODULE_TOKEN"   # ref, kind, length, no value
curl -X DELETE localhost:8080/admin/v1/credentials/CLAUDE_OAUTH_TOKEN -H "Authorization: Bearer $MODULE_TOKEN"
```

Names are CAPITAL_SNAKE_CASE (`CLAUDE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`); the table and the API both enforce `^[A-Z][A-Z0-9_]{1,63}$`. Refs fetched from the core keep the core's `cred:<slug>` form. `kind` is `claude_oauth_token` (subscription) or `anthropic_api_key` (api_key). A job whose `agent.auth.credential_ref` names a stored credential is accepted even when the job does not list it in `credentials`.

## Editable prompts (D16 / C40)

Runtime prompts live in database `video` (`prompt_versions`, `prompt_active`, `prompt_audit`). The files in
`prompts/` are only the seed: at startup every packaged version the database lacks is inserted and, for a step
with no active version, the newest is activated. Existing rows are never overwritten.

- Versions are immutable. To change a prompt, create a new version and activate it:
  `POST /admin/v1/prompts/{step}` `{version, claude_md, task_md, note}`, then
  `PUT /admin/v1/prompts/{step}/active` `{version}` with `If-Match: <revision>` (revision from
  `GET /admin/v1/prompts`). `GET /admin/v1/prompts/{step}/{version}` returns the text,
  `GET /admin/v1/prompts/audit` the history. Same bearer token as `/v1/jobs`; `X-Actor` names the editor.
- `settings.prompt_versions[step]` is `active` (default) or a pinned `MAJOR.MINOR.PATCH` (golden runs pin).
- A new version may only use placeholders the step already supplies. Placeholders are `{name}`, as in the
  reviewed spec (the contract text says `{{name}}`; unresolved, see the open questions).
- The resolved version and sha256 go to `provenance.prompts` and `provenance.prompt_refs`, and into the step's
  input hash, so an edited prompt never hits the step cache.

## Ideas (D21)

Ideas and topics live in database `video` (`topics`, `ideas`, `idea_revisions`, `idea_outbox`, `amqp_inbox`);
core keeps only the opaque `idea_ref` (`idea:<id>:v<rev>`). Spec: `docs/IDEAS.md`, schemas: `contracts/` (vendored
in `src/mvideo/ideas/schemas/`, a test fails when they drift).

- **Job input** is `input.idea_ref {id, rev}`; `input.idea` is gone. Intake loads the document (from the
  snapshot written at dispatch, else the live row when its content is frozen) and answers 422 `input_invalid`
  when it is missing; the run loads it into `ctx.idea`, and the steps read title, description and guidance
  from it (`{idea_text}`, `/in/idea.json`). The document hash goes into the step input hash and into
  `provenance.idea`.
- **Scheduler**: every `VIDEO_IDEAS_TICK_S` (5) it takes `queued` ideas of active topics by priority, queue
  time and id (advisory lock, `SKIP LOCKED`), up to `VIDEO_IDEAS_MAX_DISPATCH` (5) per pass and
  `VIDEO_IDEAS_MAX_IN_FLIGHT` (3, dispatched + in production). One transaction writes the snapshot, the
  `idea.ready` outbox row (message id `UUIDv5(NS, idea_ref)`, orchestration hints only) and sets `dispatched`.
  An invalid document marks the idea `failed` (`idea_invalid`). `VIDEO_IDEAS_PAUSED=true` stops it.
- **Relay** publishes outbox rows to `manufacture.events` (routing key `idea.ready`) with confirms; rows
  published before an error stay marked.
- **Status consumer**: queue `module.video.idea-status` (quorum, DLQ) bound to `idea.in_production`,
  `idea.done`, `idea.failed`. Inbox dedup on `message_id`; transitions are monotonic and a wrong revision or a
  late event is `stale`.
- The loops start only when `MODULE_AMQP_URL` is set (`MODULE_AMQP_PREFIX` for test isolation). They use the
  `aio-pika` package (imported lazily). Covered by `tests/test_ideas_rabbit.py` (docker marker, image `rabbitmq:4-management`).
- Seed ideas by SQL as in `docs/IDEAS.md` section 9; admin HTTP for ideas comes later.

## Develop

```bash
uv sync
make check        # ruff, mypy --strict (mvrender), import-linter, pytest
uv run pytest -m docker   # only the tests that need Docker (postgres:17 and rabbitmq:4-management images)
```

- Tests use real PostgreSQL (testcontainers), MinIO/moto, and a recording fake core. Docker tests skip when no daemon or image is present.
- CI: `.github/workflows/module-video.yml` runs ruff, mypy, import-linter, the contract tests and the full suite on every PR that touches `video-modules/module-video/` or `contracts/`.
- Layout: `src/mvideo` (service), `src/mvrender` (standalone renderer, imports nothing from `mvideo`), `prompts/` (packaged prompt versions, seeded into the database), `reference/create_database/` (the reference scenario), `agent/` (agent image), `fonts/` (Inter and JetBrains Mono, open fonts only).
- Approved frames for the render tests are in `tests/approved/`; regenerate them with `UPDATE_APPROVED=1 uv run pytest tests/test_render.py` after an intended visual change.

## Status

Verified by tests: intake and runner (leases, resume, cache, cancel), the media steps with replayed agents, render and mux on the reference, revise mode, editable prompts, ideas against a real RabbitMQ, credentials, metrics, budgets and limits.

Not verified yet:

- A run with the real Claude (needs a token in the `credentials` table; `uv run mvideo agent-smoke --image video-agent:dev` checks the agent container first). `agent/prices.json` holds placeholder prices: replace them from the current pricing page.
- The package step on a full-length render, golden-revise cases with the real Claude, and an end-to-end run with the real core.
- The Compose file and the module image (ffmpeg from apt) have not been built or started yet. `uv.lock` has not been regenerated since the OpenTelemetry SDK and exporter were added to `pyproject.toml`: run `uv lock` (needs network) before building the image, until then tracing stays a no-op and `tests/test_tracing.py` skips.
- Not implemented: `/admin/v1/runs` and `/admin/v1/golden`, the janitor for old artifacts, the Compose end-to-end test and `tests/TRACEABILITY.md`.
- Delivery of the video as a signed link: the module writes `final.en.mp4` to its bucket (`video/mp4`, sha256 in object metadata) and returns an `s3://` ref; links are issued by the storage side.

## Build history

### B8: the real steps

`MVIDEO_PIPELINE=real` replaces the fake pipeline with analysis, research, script (agent steps), capture
(agent plan, then the sandbox runs it, with fix rounds), render and package (agent writes `post.en.json`,
the module renders caption and hashtags, muxes, levels and checks). Prompts live in `prompts/<step>/<version>/`
and are copied verbatim from the spec by `node scripts/extract_prompts.js`; do not edit them by hand.

Not verified yet: a run with the real Claude (needs `CLAUDE_CODE_OAUTH_TOKEN`, see `mvideo agent-smoke`) and the
full package step on a complete 160 s render. `capture_status` is not derived (the script schema has no
`expect_error`). Core's `cover`/`contact_sheet` are artifact objects while the module sends refs as strings.

### B9: revise mode

A `revise` job runs `revise_pipeline()`: `script-revise` (minimal edit by the agent, `changes.en.json` checked
against the structural diff, rule `revise_diff`), capture (reused unless commands or capture names changed, then
no sandbox starts), render, package (the post text is reused unless `meta.hook` or the first captions changed).
Analysis and research come from the last succeeded run of the production; the pinned commit is never
re-resolved. `output.changes` is rendered from `changes.en.json` plus "values changed".

Not verified: golden-revise-1..4 against the real Claude (replay and unit tests only).
