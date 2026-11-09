# module-video

Stage `video`: idea → finished English video (Python 3.12).

Ideas/topics backlog ownership and the `idea.ready` scheduler: see [`docs/IDEAS.md`](docs/IDEAS.md) (D21).

Specification: `../docs/module-video/` (`module-video-01-description.docx` … `module-video-06-prompts.docx`). Build phases B0–B12 are in `module-video-06-prompts`.

## Status

- B0 done: service skeleton, `/info` `/health` `/ready` `/metrics`, bootstrap config, settings and contract models.
- B1 done: database `video` (8 tables, one Alembic revision run at start-up under an advisory lock), async repositories (idempotent `create_run`, leases, step upsert and reuse lookup, `add_cost`).
- B2 done: `POST /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel` (bearer auth), core client behind a swappable `CoreGateway` (HTTP contract 1), runner and worker with leases, step cache, cancel, restart recovery, usage gates. The pipeline is made of fake steps that write small files to S3 until B7/B8. `/ready` reports `auth: missing` until a job has fetched a matching credential.
- B3 done: JSON Schemas of every agent file (`src/mvideo/validate/schemas`, extracted from the contracts spec), the rules of 04 §4.3, §5.2 and §6.1, `mvideo validate DIR [--src DIR]`, and `mvrender.timing` shared by validator and renderer. The reference scenario is in `reference/create_database/` (ported by hand from the original renderer); its estimated length is within 1 % of the original.
- Known limits of B3: `caption_fit` and `note_fit` use an estimated glyph width until the renderer brings real font metrics (B4); a typed-but-never-run command (the original hook scene) cannot be expressed, so the hook scene shows an annotation line instead.
- B4 done (stills): `mvrender` resolves script + capture + source into frames: palette, fonts (Inter and JetBrains Mono in `fonts/`, copied to `/usr/share/fonts/manufacture` in the image), layout, safe zone, terminal, debugger, diagram elements, glyph and safe-zone checks, `mvrender preview DIR --src DIR --at ...`, `mvrender sheet` (contact sheet with the safe-zone overlay). The reference renders from `reference/create_database/` with source excerpts in `reference/create_database/sources/`; approved frames are in `tests/approved/` (SSIM >= 0.98).
- B5 done (video and sound): `mvrender render DIR --src DIR --out OUT` renders `video.en.mp4`, `cover.en.jpg` and `sfx.en.wav`. Cues come from animation events (`cues.py`, one cue per event, checked within one frame), sound is synthesized with seeded randomness (`sfx.py`), chunks are encoded in parallel by single-threaded x264 and joined with `-c copy` (`encode.py`; 1, 4 and 8 workers give identical bytes). The sound is leveled to -14 LUFS under a -1 dBTP ceiling with a limiter and measurement loop (sparse effects cannot reach the target by linear gain, so `loudnorm` is used only to measure). Reference: 9817 frames in 181 s on 8 workers (1.11 s per video second), -14.3 LUFS, -1.8 dBTP. ffmpeg comes from `$FFMPEG`, PATH or the dev dependency `imageio-ffmpeg`; the image installs it with apt.
- B6 done (sandbox): `mvideo.sandbox` has `templates.py` (container spec from settings: digest required, network none, read-only root, tmpfs, cap_drop ALL, no-new-privileges, no binds, no privileges), `sessions.py` (long-lived psql on a pty with sentinel prompts, sh on pipes with an `$?` sentinel, merged output) and `executor.py` (plan to `capture.json` through the Docker SDK at `DOCKER_HOST`; containers removed after the run). Docker tests are marked `docker` (`uv run pytest -m docker`; they need a daemon and the local image `postgres:17`, otherwise they skip). Image entries may set `exec_user` (session user, `postgres` for the Postgres image). `ready_cmd` for Postgres must use TCP (`pg_isready -h 127.0.0.1 -U postgres`), because the entrypoint's temporary server listens on the socket only. The reference plan was corrected: a hidden `ROLLBACK;` after the failed transaction, and `n_relations` counts non-shared relations with storage (222), not all of `pg_class` (415).
- B7 done (agent runtime): `agent/Dockerfile` builds `video-agent` (build: `docker build -f agent/Dockerfile -t video-agent:dev .`; the Claude Code CLI is bundled in `claude-agent-sdk`, pinned 0.2.179 / CLI 2.1.319, both recorded in `_result.json` for provenance). `mvideo.agents`: `runtime.py` (SDK session in the container; MCP tools `validate`, `estimate`, `source_line`), `launcher.py` (workspace volumes, closed container spec, egress listener per step, `DockerLauncher`; `ReplayLauncher` selected by `MVIDEO_FAKE_AGENT=replay` + `MVIDEO_REPLAY_DIR`, scenarios `ok`, `rate_limit`, `auth_failed`, `max_turns`, `budget`), `outcomes.py` (blocked.json, auth to blocked `agent_auth_failed`, limits to transient `agent_rate_limited` with `retry_after`, turns, budget), `auth.py` (exactly one of `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` by `agent.auth.mode`, never both; value from the core, memory only, scrubbed from transcripts), `run.py` (cost: SDK number in `usd` mode, estimate from usage otherwise; `agent/prices.json` holds UNVERIFIED placeholder prices, replace them from the current pricing page). `mvideo.net.egress_proxy` (CONNECT only, port 443, per-step allowlist, denials counted), `mvideo.sources.git_cache` (pinned checkouts in named volumes, LRU eviction), `mvideo.api.mcp_sandbox` (`sandbox_try`, per-step bearer token, scratch sandbox destroyed at step end). SDK option values live in settings (`agent.permission_mode`, `agent.setting_sources`, `agent.disallowed_tools`). Verified against a real Anthropic endpoint with an invalid token: container, proxy and SDK run and the 401 maps to `auth_failed`. NOT yet verified: a run with a real token (needs `claude setup-token`): `CLAUDE_CODE_OAUTH_TOKEN=... uv run mvideo agent-smoke --image video-agent:dev`.
- Next: B5 cues, sound, parallel encode and loudness (needs ffmpeg).

## Develop

```bash
uv sync
make check        # ruff, mypy --strict (mvrender), import-linter, pytest (database tests need Docker)
uv run mvideo     # needs the bootstrap variables of docs 03 section 6
docker build -t module-video:dev .
```

Settings never come from the environment: they arrive with each job (settings snapshot). `/info` serves the JSON Schemas generated from `src/mvideo/settings_model.py` and `src/mvideo/contract.py`.

Note: core now carries jobs over RabbitMQ (core-04 section 15). The job intake in B2 follows whichever contract core has implemented; B1 and B3–B6 do not depend on it.

## B8: the real steps

`MVIDEO_PIPELINE=real` replaces the fake pipeline with analysis, research, script (agent steps), capture
(agent plan, then the sandbox runs it, with fix rounds), render and package (agent writes `post.en.json`,
the module renders caption and hashtags, muxes, levels and checks). Prompts live in `prompts/<step>/<version>/`
and are copied verbatim from the spec by `node scripts/extract_prompts.js`; do not edit them by hand.

Not verified yet: a run with the real Claude (needs `CLAUDE_CODE_OAUTH_TOKEN`, see `mvideo agent-smoke`) and the
full package step on a complete 160 s render. `capture_status` is not derived (the script schema has no
`expect_error`). Core's `cover`/`contact_sheet` are artifact objects while the module sends refs as strings.

## B9: revise mode

A `revise` job runs `revise_pipeline()`: `script-revise` (minimal edit by the agent, `changes.en.json` checked
against the structural diff, rule `revise_diff`), capture (reused unless commands or capture names changed, then
no sandbox starts), render, package (the post text is reused unless `meta.hook` or the first captions changed).
Analysis and research come from the last succeeded run of the production; the pinned commit is never
re-resolved. `output.changes` is rendered from `changes.en.json` plus "values changed".

Not verified: golden-revise-1..4 against the real Claude (replay and unit tests only).

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

## Credentials in the module database

For a local deployment the Claude credential lives in this module's database (table `credentials`, migration 0005). The module looks there first and asks the core only when the ref is not stored. Values are kept as plain text, so use this only on a machine you own. The API never returns a value, and the logs and `repr` never show it.

```bash
curl -X PUT localhost:8080/admin/v1/credentials/claude-main \
  -H "Authorization: Bearer $MODULE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"claude_oauth_token","value":"'"$TOKEN"'","note":"local"}'   # 201 new, 204 replaced
curl localhost:8080/admin/v1/credentials -H "Authorization: Bearer $MODULE_TOKEN"   # ref, kind, length, no value
curl -X DELETE localhost:8080/admin/v1/credentials/claude-main -H "Authorization: Bearer $MODULE_TOKEN"
```

`kind` is `claude_oauth_token` (subscription) or `anthropic_api_key` (api_key). A job whose `agent.auth.credential_ref` names a stored credential is accepted even when the job does not list it in `credentials`.
