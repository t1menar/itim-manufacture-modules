module.exports = {
  dir: 'module-video', file: 'module-video-03-technical.docx',
  meta: { title: 'module-video — Technical design', subtitle: 'Stack, layout, renderer refactor, agent runtime, sandbox, data model, deployment, observability, security, tests',
    doc: 'module-video-03-technical', version: '0.2', status: 'Draft', date: '2026-11-08' },
  blocks: [
['h1', '1. Overview'],
['p', 'The module is one Python service (`module-video` container) plus three kinds of short-lived containers it starts through Docker: **agent** containers (one per Claude step), **sandbox** containers (the system being explained, e.g. PostgreSQL 17) and **helper** containers (source checkout). The deterministic renderer `mvrender` runs inside the module container as a pool of worker processes.'],
['code', `                 core ──POST /v1/jobs──▶ module-video (FastAPI, runner, renderer pool, egress proxy, MCP gateway)
                   ▲                         │            │                 │
          callbacks│                         │Docker API  │S3               │SQL
                   └─────────────────────────┤ (socket    ▼                 ▼
                                             │  proxy)  MinIO          PostgreSQL "video"
             ┌───────────────────────────────┼────────────────────────┐
             ▼                               ▼                        ▼
   video-agent container           sandbox container          helper container
   (Claude Agent SDK, CLI)         postgres:17@sha256:…       git clone → src volume
   net: video-agents (internal)    net: none                  net: video-agents
   exit only via module proxy      reached by docker exec     exit only via module proxy`],
['h1', '2. Stack'],
['table', ['Area', 'Choice and version', 'Why'], [
  ['Language', 'Python 3.12', 'system rule for modules; the reference renderer is Python'],
  ['HTTP', 'FastAPI 0.115+, Uvicorn, Pydantic v2', 'typed request models generate the JSON Schemas served in `/info`'],
  ['DB', 'SQLAlchemy 2 (async) + asyncpg, Alembic', 'standard, migrations in the service folder'],
  ['HTTP client', 'httpx (async) with tenacity retries', 'core callbacks, credentials'],
  ['S3', 'aioboto3 / boto3 against MinIO', 'multipart upload of large videos'],
  ['Claude', '`claude-agent-sdk` (Python) inside the agent image, which bundles or requires the Claude Code CLI; pinned versions recorded in provenance', 'the system decision: Claude Code via the Agent SDK. Option names in this document: verify against current documentation.'],
  ['Docker', '`docker` Python SDK 7.x, talking to `tecnativa/docker-socket-proxy`', 'create/exec/archive/remove containers'],
  ['Validation', '`jsonschema` 4.x (Draft 2020-12) + own rule checks', 'same validator in agent tool and module'],
  ['Rendering', 'Pillow 11, NumPy 2, fontTools 4, SciPy (`signal.lfilter`), ffmpeg 7.x static build (libx264, AAC, loudnorm, ebur128)', 'reference stack; SciPy replaces the per-sample Python filter loops in `sfx.py`'],
  ['Fonts', 'Inter 4.x (OFL), JetBrains Mono 2.304 (OFL); static TTFs, sha256-pinned at image build', 'open fonts only, Cyrillic-ready for later'],
  ['Observability', 'prometheus-client, structlog (JSON), OpenTelemetry SDK + OTLP exporter', 'system rule'],
  ['Tests', 'pytest, pytest-asyncio, respx, testcontainers (PostgreSQL, MinIO), hypothesis for timing', 'unit to integration'],
  ['Lint', 'ruff, mypy --strict for `mvrender` and validators, import-linter', 'renderer and validators encode rules'],
], [1, 3, 2.4]],
['h1', '3. Package layout'],
['code', `module-video/
  pyproject.toml               # two packages: mvideo (service), mvrender (renderer)
  Dockerfile                   # module image: python, ffmpeg, fonts, mvrender
  agent/Dockerfile             # video-agent image: python, claude-agent-sdk, Claude Code CLI, git, rg
  agent/runner.py              # entrypoint inside agent container (reads /job/run.json)
  alembic/                     # migrations
  src/mvideo/
    app.py                     # FastAPI app, lifespan (DB, S3, Docker, proxy, janitor)
    api/ info.py jobs.py health.py admin.py problems.py
    config.py                  # bootstrap env only
    settings_model.py          # Pydantic model of settings (source of settings_schema)
    db/ models.py repo.py
    core_client.py             # callbacks, credentials, productions
    storage.py                 # S3 paths, upload with sha256
    pipeline/ runner.py state.py cache.py budget.py
    pipeline/steps/ analysis.py research.py script.py capture.py render.py package.py revise.py
    agents/ workspace.py prompts.py launcher.py results.py
    net/ egress_proxy.py       # CONNECT proxy, per-step port and allowlist
    mcp/ gateway.py            # HTTP MCP server: sandbox_try (capture only)
    sandbox/ templates.py docker_api.py sessions.py executor.py
    sources/ git_cache.py
    validate/ cli.py schemas/ rules_script.py rules_research.py rules_capture.py rules_post.py
    checks/ runner.py          # wraps mvrender checks + ffprobe/ebur128 checks
    observability/ metrics.py logging.py tracing.py
  src/mvrender/
    scenario.py                # load + validate format id
    resolve.py                 # script + capture + sources -> resolved
    timing.py                  # shared with validator
    timeline.py                # events, marks, cues
    layout.py safezone.py fonts.py palette.py
    draw/ canvas.py captions.py notes.py terminal.py debugger.py diagram.py title.py elements.py highlight_c.py highlight_sh.py
    cues.py sfx.py encode.py sheet.py cover.py checks.py cli.py
  prompts/<step>/<version>/  CLAUDE.md  task.md  meta.json
  prompts/skills/explainer-video/<version>/SKILL.md
  reference/create_database/  analysis.json research.json script.en.json capture.plan.json capture.json sources/
  golden/ ideas.json           # golden set
  tests/`],
['h1', '4. Renderer refactor plan'],
['p', 'Source: `create-database-video/render.py` (976 lines), `sfx.py`, `make_en.py`. The drawing code (window frames, C highlighter, terminal state machine, debugger layout, notes, folders, pills, arrows, cylinders) is kept and moved into `mvrender.draw`; everything that is content (scenes, steps, strings, line numbers, cue rules tied to lines, diagram kinds) is removed and replaced by the scenario.'],
['h2', '4.1 Mapping of reference code to modules'],
['table', ['Reference', 'Becomes', 'Change'], [
  ['palette constants `PAGE`, `INK`, `ORANGE`, … `C_KW`…', '`palette.py` from settings `palette`', 'tokens by name; defaults = reference values'],
  ['`av()`, `sfm()` with macOS font paths, `F_*` constants', '`fonts.py` role table (`caption`, `note_term`, `note`, `term`, `code`, `code_current`, …) → Inter / JetBrains Mono files', 'sizes from the reference (caption 60 Bold, terminal 27 Regular, code 22 Regular / 22 SemiBold, …); weights mapped Demi → SemiBold, Heavy → ExtraBold'],
  ['`MID`, `PANEL`, `NOTE_Y`, `TERM_*`, `CODE_*`', '`layout.py`', 'same geometry; `TERM_COLS` and `CODE_COLS` recomputed from JetBrains Mono advance width'],
  ['`Term` class (cmd/out/wait/mark/prompt, `state(t)`)', '`draw/terminal.py` + `timeline.py`', 'built from scenario events; outputs from capture; marks named `<cmd>.typed`, `<cmd>.output`'],
  ['`highlight_cmd`, `out_line`, `wrap_out`', '`draw/highlight_sh.py`', 'SQL keyword set and tool names from a table, not a fixed set; `[[…]]` from scenario `highlight`'],
  ['`SRC`, `src_line`, `expect`, `highlight_c`', '`resolve.py` (lines from `/src` at commit) + `draw/highlight_c.py`', '`expect` checked in resolve; highlighter unchanged'],
  ['`Step`, `layout_step`, `Debugger` (`seq_time`, `line_time`)', '`draw/debugger.py` + `timing.step_duration()`', 'loops expanded from `loop` with iteration count from capture'],
  ['`Scene`, `seq_notes`, `build_scenes()`', '`timeline.py`', 'scene durations from `timing`; no Python per scene'],
  ['`diagram(kind)` branches, `folder`, `pill`, `arrow`, `cylinder`, `code_card`, `draw_concept`', '`draw/elements.py` + `draw/diagram.py`', 'element vocabulary on layouts `single`, `row2`, `row3`, `row4`, `pair`'],
  ['`to_reels`, `SAFE_*`, `_dots`', '`safezone.py`', 'scale and offset derived from settings; every box recorded for the check'],
  ['`sound_cues()` with hard-coded line numbers', '`cues.py`', 'rules per event kind (table 4.4) + element `sound`'],
  ['`sfx.py` synth functions', '`sfx.py`', 'same sounds; filters vectorized with `scipy.signal.lfilter`; RNG seeded per cue index'],
  ['`main()` single ffmpeg pipe', '`encode.py`', 'chunked parallel workers + concat'],
  ['`make_en.py`, `render_en.py`', 'removed', 'English is written directly; the English strings of the reference become `reference/create_database/script.en.json`'],
], [2.2, 2, 2.4]],
['h2', '4.2 Data flow inside the renderer'],
['ol', [
  '`scenario.load(script.en.json)` checks `format` = `manufacture.scenario/1` and the JSON Schema.',
  '`resolve.resolve(script, capture, src_root, settings)` fills every capture reference, attaches verbatim source lines for every range and code card, checks every `expect`, expands loops, fills `{name}` placeholders in text, and writes `resolved.en.json`. Any miss raises a typed error (`capture_missing`, `expect_mismatch`, `source_missing`).',
  '`timeline.build(resolved, timing_settings, reading_wps)` computes scene starts, events, marks, note windows, element appear/disappear times and the cue list; writes `timeline.en.json`.',
  '`checks.static(resolved, timeline)` runs glyph, text-fit, safe-zone, numbers and term-note checks without drawing a frame (fast fail).',
  '`encode.render(timeline, workers)` renders frames; every `canvas.text()` call records `(font_role, string)` and every box; the dynamic glyph and safe-zone checks run on these records.',
  '`cues.from_timeline()` → `sfx.synthesize()` → `sfx.en.wav`; `checks.sync()` compares cues with animation events.',
  '`sheet.build()` and `cover.extract()` render selected frames directly from `render(T)`.',
]],
['h2', '4.3 Fonts and glyph checks'],
['ul', [
  'Font files live in `/usr/share/fonts/manufacture/` in the image: `Inter-{Regular,Medium,SemiBold,Bold,ExtraBold}.ttf`, `JetBrainsMono-{Regular,Medium,SemiBold,Bold}.ttf`; their sha256 are in `fonts.lock` and in provenance.',
  'Fonts are loaded only through `fonts.get(role)`; `ImageFont.truetype` with any other path is forbidden by a lint rule. There is no fallback font: Pillow draws `.notdef` for missing glyphs, which is why the check is needed.',
  'Static check: every string in `resolved` with its role is tested against the cmap (`fontTools.ttLib.TTFont(path).getBestCmap()`); dynamic check: every `canvas.text()` call during rendering is tested too (cached per `(role, char)`). Threshold: 0 missing glyphs. The error lists character, code point, role and the scene id.',
  'Known gaps to avoid in prompts: "⋮", "↪" in JetBrains Mono (verify with the check; the prompt asks to use words instead).',
]],
['h2', '4.4 Sound from cues'],
['table', ['Timeline event', 'Cue kind (param)', 'Note'], [
  ['scene start (not first)', '`whoosh` (0.6)', ''],
  ['hook accent (`hook.impact_line`)', '`impact` (1)', 'first scene only'],
  ['typed character (not space)', '`key` (variation by index)', 'one per character'],
  ['command typed complete', '`enter` (1)', 'not in the hook scene'],
  ['first non-empty output line after a command', '`blip` (1)', ''],
  ['output line starting with `ERROR`', '`error` (1)', 'replaces `blip`'],
  ['debugger enter / resume', '`tape_stop` at enter − 0.2 s / `tape_start` at resume − 0.25 s', ''],
  ['debugger step start', '`ding` (1 + (k mod 5) × 0.125)', 'pitch rises per step'],
  ['debugger current line changes', '`tick` (1, or 0.5 inside fast loop iterations)', ''],
  ['loop iteration start / end', '`whoosh` (0.15) / `block` ((i mod 4)/3)', ''],
  ['diagram element appear', 'element `sound` or default per type (`pop` for folder, pill, cylinder, code card; none for label, arrow)', '`pop` pitch rises with slot'],
  ['element with `success: true` appear', '`chime`', ''],
  ['ambient pad', 'whole duration, level −31 dBFS', 'setting `audio.ambient_pad`'],
], [2.4, 2.4, 1.6]],
['p', 'Master: soft limiter `tanh(1.4x)/tanh(1.4)`, peak −1 dBFS, 48 kHz stereo 16-bit WAV. The loudness target is applied in packaging, not here.'],
['h2', '4.5 Safe zone'],
['p', 'Content is laid out on the full 1080×1920 canvas (reference geometry). The layout region `layout.src_rect` (default `(0, 150, 1080, 1590)`) is scaled uniformly to fit the safe rectangle `(left, top, 1080 − right, 1920 − bottom)` from `video.safe_zone` (default 72, 220, 108, 400) and pasted there; the background outside keeps the page colour and dot grid. Every drawn box is transformed and must lie inside the safe rectangle (tolerance 0 px). The contact sheet draws the covered areas as translucent red bands.'],
['h2', '4.6 Parallel chunked render and ffmpeg settings'],
['ul', [
  'Frames are a pure function `render(T)` of the timeline, so the frame range `[0, N)` with `N = round(total_s × fps)` is cut into chunks of `render.chunk_s × fps` frames (default 10 s = 600 frames, a multiple of the GOP).',
  'A `ProcessPoolExecutor` with `render.workers` processes (0 = `min(cpu_count, 8)`) renders chunks; each worker pipes raw RGB24 frames into its own ffmpeg producing `chunk_NNNN.mp4`.',
  'Per chunk: `ffmpeg -f rawvideo -pix_fmt rgb24 -s 1080x1920 -r 60 -i - -c:v libx264 -preset {video.preset} -crf {video.crf} -maxrate {video.max_bitrate_kbps}k -bufsize {2×max}k -profile:v high -level 4.2 -pix_fmt yuv420p -g {fps×gop_s} -keyint_min {fps×gop_s} -sc_threshold 0 -colorspace bt709 -color_primaries bt709 -color_trc bt709 -an chunk.mp4` (defaults: medium, 17, 24000, 2 s).',
  'Concat: `ffmpeg -f concat -safe 0 -i chunks.txt -c copy -movflags +faststart video.en.silent.mp4`; then `ffprobe -count_frames` must equal N.',
  'Determinism: `-threads 1` per chunk encoder and fixed x264 parameters make chunks byte-identical across runs; parallelism comes from processes.',
  'Final mux (package): `ffmpeg -i video.en.silent.mp4 -i sfx.en.wav -map 0:v -map 1:a -c:v copy -af loudnorm=I=-14:TP=-1:LRA=11:measured_I=…:measured_TP=…:measured_LRA=…:measured_thresh=…:offset=…:linear=true -ar 48000 -ac 2 -c:a aac -b:a {audio.bitrate_kbps}k -shortest -movflags +faststart final.en.mp4` after a first pass `loudnorm=…:print_format=json`; verified with `ebur128=peak=true`.',
]],
['h1', '5. Agent runtime and sandbox'],
['h2', '5.1 Agent container'],
['table', ['Aspect', 'Design'], [
  ['Image', '`video-agent` (built from `module-video/agent/Dockerfile`), pinned by digest in settings `agent.image`; contains Python 3.12, `claude-agent-sdk`, Claude Code CLI, git, ripgrep, the validator (`mvideo.validate` + `mvrender.timing`), non-root user `agent` (uid 10001)'],
  ['Mounts', '`/work` (rw, cwd: `CLAUDE.md`, `.claude/skills/…`, `task.md`), `/in` (ro, step inputs), `/src` (ro, source cache volume at the commit), `/ref` (ro, reference scenario), `/out` (rw, outputs); all named volumes or archive copies, no host paths'],
  ['Env', 'exactly one auth variable, by `agent.auth.mode`: `CLAUDE_CODE_OAUTH_TOKEN` (subscription; token from `claude setup-token`) or `ANTHROPIC_API_KEY` (api_key); never both (verify variable names against current documentation); `HTTPS_PROXY=http://module-video:<step port>`, `NO_PROXY=module-video`, `MANUFACTURE_MCP_URL` (capture only), `CLAUDE_CONFIG_DIR=/work/.claude-home`'],
  ['Network', 'Docker network `video-agents` with `internal: true`: no route out; module-video is attached to it and runs the egress proxy and the MCP gateway'],
  ['Limits', '`agent.cpus` 1, `agent.memory_mb` 2048, `agent.pids` 256, read-only root fs with tmpfs `/tmp`, `no-new-privileges`, all capabilities dropped'],
  ['Entrypoint', '`python /opt/agent/runner.py /job/run.json`: builds `ClaudeAgentOptions` from `run.json`, runs one SDK session, streams every message as JSON lines to `/out/_transcript.jsonl`, writes `/out/_result.json` (session id, turns, cost, usage, stop reason)'],
], [1, 5.4]],
['h2', '5.2 Claude Agent SDK usage per step'],
['note', 'Option names (`cwd`, `allowed_tools`, `disallowed_tools`, `permission_mode`, `max_turns`, `max_budget_usd`, `setting_sources`, `mcp_servers`, `model`, `resume`) and the result fields (`total_cost_usd`, `usage`, `num_turns`, `session_id`) follow the Python SDK as known at the time of writing: **verify against current documentation**. All values come from settings, so a renamed option needs only a runner change.'],
['table', ['Step', 'cwd / CLAUDE.md', 'Allowed tools', 'Network allowlist', 'max_turns / budget USD / timeout'], [
  ['analysis', '`/work`, `prompts/analysis/<v>/CLAUDE.md`', '`Read`, `Glob`, `Grep`, `Write`, `WebFetch`, `WebSearch`, `mcp__manufacture__validate`', 'Anthropic + `network.allow_domains.analysis`', '20 / 1.0 / 600 s'],
  ['research', '`/work`, `prompts/research/<v>/CLAUDE.md`', '`Read`, `Glob`, `Grep`, `Write`, `WebFetch`, `WebSearch`, `mcp__manufacture__validate`, `mcp__manufacture__source_line`', 'Anthropic + `network.allow_domains.research`', '60 / 4.0 / 1500 s'],
  ['script', '`/work`, `prompts/script/<v>/CLAUDE.md`', '`Read`, `Glob`, `Grep`, `Write`, `Edit`, `mcp__manufacture__validate`, `mcp__manufacture__estimate`', 'Anthropic only', '40 / 3.0 / 1200 s'],
  ['capture', '`/work`, `prompts/capture/<v>/CLAUDE.md`', '`Read`, `Write`, `Edit`, `mcp__manufacture__validate`, `mcp__sandbox__sandbox_try`', 'Anthropic only (sandbox has no network)', '40 / 2.0 / 1200 s'],
  ['package', '`/work`, `prompts/package/<v>/CLAUDE.md`', '`Read`, `Write`, `mcp__manufacture__validate`', 'Anthropic only', '10 / 0.3 / 300 s'],
  ['script-revise', '`/work`, `prompts/script-revise/<v>/CLAUDE.md`', 'as script', 'Anthropic only', '30 / 2.0 / 900 s'],
], [0.9, 1.6, 2.2, 1.4, 1.2]],
['ul', [
  '`Bash` is never allowed; `disallowed_tools` lists `Bash`, `NotebookEdit`, `Task` explicitly. `permission_mode` is the non-interactive mode that denies anything not allowed (verify the value name).',
  '`setting_sources=["project"]` so the step\'s `CLAUDE.md` and skill in `/work` are loaded and no user-level settings are; `system_prompt` uses the Claude Code preset.',
  '`mcp__manufacture__*` tools are an in-process SDK MCP server inside the runner (validator, estimate, source line lookup); `mcp__sandbox__sandbox_try` is an HTTP MCP server on the module, reachable only from the capture container with a per-step token.',
  'Validation retries resume the same session (`resume=<session_id>`) with the validator output as the new prompt, so the agent keeps its context.',
  'Model: `models.<step>` or `model` (default `claude-opus-5-5`).',
]],
['h2', '5.3 Egress proxy'],
['p', '`mvideo.net.egress_proxy` is an asyncio HTTP CONNECT proxy inside the module. For each agent or helper container the module opens a listener on a free port from `network.proxy_ports` (default 3200–3299) bound to the `video-agents` interface, with that step\'s allowlist (exact host or `*.domain` suffix, port 443 only). Plain HTTP requests are refused. Every decision is logged (host, allowed, bytes) and counted; the listener is closed when the container exits. No TLS interception.'],
['h2', '5.4 Sandbox'],
['table', ['Aspect', 'Design'], [
  ['Image', '`sandbox_images.<key>.image` must contain `@sha256:`; pulled once by digest; the digest is recorded in `capture.json` and provenance'],
  ['Container', '`--network none`, read-only root fs, tmpfs for data dirs from `sandbox_images.<key>.tmpfs` (e.g. `/var/lib/postgresql/data:size=1g`, `/tmp:size=256m`), `cpus` 2, `memory_mb` 2048 (no swap), `pids` 512, `cap_drop ALL` + `cap_add` from the image entry (postgres entrypoint needs CHOWN, SETUID, SETGID, FOWNER, DAC_OVERRIDE), `no-new-privileges`, env from the image entry (e.g. `POSTGRES_HOST_AUTH_METHOD=trust`)'],
  ['Readiness', '`ready_cmd` (e.g. `pg_isready -U postgres`) polled every 0.5 s up to `ready_timeout_s` (60)'],
  ['Version check', '`version_cmd` (e.g. `psql -U postgres -tAc "SELECT version()"`) must contain `version_expect` (e.g. `PostgreSQL 17.`)'],
  ['Sessions', 'one long-lived `docker exec -i` process per plan session; kinds `psql` (`psql -X -U postgres -d <db>` with a sentinel `\\echo` after each command and `%x` transaction state captured from a sentinel prompt) and `sh` (`bash --noprofile --norc` with sentinel `printf` and `$?`); stdout and stderr merged in order'],
  ['Timeouts', '`command_timeout_s` 60 per command, `total_timeout_s` 900 per capture'],
  ['Scratch sandboxes', '`sandbox_try` uses a separate container of the same image, at most one per capture step, destroyed at step end; its outputs are never used in the video'],
], [1, 5.4]],
['h2', '5.5 Source cache'],
['p', 'A helper container (agent image, entrypoint `git`) clones `sources.allowed_repos[i].url` with `--filter=blob:none --no-checkout`, fetches the pinned commit at depth 1 and checks it out into the named volume `video-src-<sha256(url)[:12]>-<commit[:12]>`, mounted read-only for later steps. The table `source_cache` tracks size and last use; volumes beyond `sources.cache_max_gb` are removed least-recently-used first.'],
['h1', '6. Configuration'],
['table', ['Bootstrap env var', 'Example', 'Meaning'], [
  ['`VIDEO_DATABASE_URL`', '`postgresql+asyncpg://video:…@postgres:5432/video`', 'own database'],
  ['`VIDEO_LISTEN_ADDR`', '`0.0.0.0:8080`', 'HTTP API'],
  ['`MODULE_CORE_URL`', '`http://core:8080`', 'core base URL'],
  ['`MODULE_CORE_TOKEN`', '(secret)', 'per-module token from registration'],
  ['`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`', '`http://minio:9000`, …, `manufacture`', 'object storage'],
  ['`DOCKER_HOST`', '`tcp://video-docker-proxy:2375`', 'Docker socket proxy'],
  ['`VIDEO_AGENT_NETWORK`', '`video-agents`', 'name of the internal Docker network (deployment fact)'],
  ['`OTEL_EXPORTER_OTLP_ENDPOINT`', '`http://otel-collector:4317`', 'traces'],
], [2.2, 2.4, 1.8]],
['p', 'Everything else is a setting in the job snapshot (schema in 04 §10): models, prompt versions, limits, network allowlists, repositories, sandbox images, agent image, video, audio, palette, timing, text, render, post, revise and runtime keys. The module keeps no settings of its own; jobs without settings are rejected.'],
['h1', '7. Data model (database `video`)'],
['table', ['Table', 'Columns (type)', 'Indexes and notes'], [
  ['`runs`', '`id` uuid pk, `job_id` uuid not null, `attempt` int, `production_id` uuid, `mode` text (`create`|`revise`), `language` text, `variant_id` uuid null, `status` text, `current_step` text null, `percent` int, `settings_version` int, `settings` jsonb, `input` jsonb, `deadline` timestamptz, `cost_usd` numeric(10,4), `tokens_in` bigint, `tokens_out` bigint, `result` jsonb null, `error` jsonb null, `cancel_requested` bool, `lease_owner` text null, `lease_until` timestamptz null, `created_at`, `started_at`, `finished_at` timestamptz', 'unique (`job_id`); index (`production_id`, `created_at` desc); index (`status`) where status in (accepted, running)'],
  ['`steps`', '`id` uuid pk, `run_id` uuid fk, `name` text, `try` int, `status` text, `input_hash` text, `prompt_version` text null, `model` text null, `outputs` jsonb (name → {ref, sha256, size}), `reused_from` uuid null, `error` jsonb null, `cost_usd` numeric(10,4), `tokens_in`, `tokens_out`, `cache_read_tokens`, `cache_write_tokens` bigint, `num_turns` int, `session_id` text null, `started_at`, `finished_at` timestamptz, `duration_s` real', 'unique (`run_id`, `name`, `try`); index (`input_hash`) for reuse lookup'],
  ['`checks`', '`id` bigserial, `run_id` uuid, `step_id` uuid, `check` text, `status` text (`pass`|`warn`|`fail`), `value` jsonb, `limit` jsonb, `details` jsonb, `created_at`', 'index (`run_id`)'],
  ['`sandbox_runs`', '`id` uuid, `step_id` uuid, `purpose` text (`capture`|`scratch`), `image` text, `digest` text, `version_string` text, `container_id` text, `limits` jsonb, `exit` text, `log_ref` text, `started_at`, `finished_at`', 'index (`step_id`)'],
  ['`agent_runs`', '`id` uuid, `step_id` uuid, `container_id` text, `image_digest` text, `sdk_version` text, `cli_version` text, `session_id` text, `stop_reason` text, `turns` int, `cost_usd`, `usage` jsonb, `transcript_ref` text, `egress_denied` int, `started_at`, `finished_at`', 'one row per agent invocation (incl. resumes)'],
  ['`source_cache`', '`repo_url` text, `commit` char(40), `volume` text, `size_bytes` bigint, `created_at`, `last_used_at`', 'pk (`repo_url`, `commit`)'],
  ['`usage_log`', '`id` bigserial, `kind` text (`job`|`agent_run`), `run_id` uuid, `step` text null, `at` timestamptz', 'index (`kind`, `at`); counts for `limits.max_jobs_per_day` (calendar day UTC) and `limits.max_agent_runs_per_hour` (sliding hour); rows older than 7 days deleted by the janitor'],
  ['`golden_runs`', '`id` uuid, `requested_by` text, `overrides` jsonb, `status`, `report` jsonb, `created_at`, `finished_at`', 'admin golden-set runs'],
], [0.9, 4, 1.6]],
['p', 'Migrations: Alembic, forward-only, one revision per change, run at startup under an advisory lock; a release may only add nullable columns or new tables (expand), removals follow one release later (contract). Run data older than `runtime.retention_days` (default 180) is deleted by the janitor; S3 objects follow the system retention rule (intermediate files 30 days).'],
['h1', '8. Observability'],
['table', ['Metric', 'Type', 'Labels'], [
  ['`video_jobs_total`', 'counter', '`mode`, `status` (succeeded, failed, blocked, cancelled)'],
  ['`video_job_duration_seconds`', 'histogram', '`mode`'],
  ['`video_step_duration_seconds`', 'histogram', '`step`'],
  ['`video_step_failures_total`', 'counter', '`step`, `class`, `code`'],
  ['`video_step_reused_total`', 'counter', '`step`'],
  ['`video_schema_retries_total`', 'counter', '`step`'],
  ['`video_fix_rounds_total`', 'counter', '`check`'],
  ['`video_blocked_total`', 'counter', '`step`'],
  ['`video_agent_turns`', 'histogram', '`step`'],
  ['`video_tokens_total`', 'counter', '`step`, `kind` (input, output, cache_read, cache_write)'],
  ['`video_cost_usd_total`', 'counter', '`step`, `model`, `estimated` (true/false)'],
  ['`video_agent_auth_failures_total`, `video_rate_limited_total`', 'counter', '`step`'],
  ['`video_jobs_today`, `video_agent_runs_last_hour`', 'gauge', '—'],
  ['`video_cost_usd`', 'histogram (per job)', '`mode`'],
  ['`video_egress_denied_total`', 'counter', '`step`'],
  ['`video_sandbox_seconds`', 'histogram', '`purpose`'],
  ['`video_render_seconds_per_video_second`', 'histogram', '—'],
  ['`video_render_frames_total`', 'counter', '—'],
  ['`video_check_failures_total`', 'counter', '`check`'],
  ['`video_missing_glyphs_total`', 'counter', '`role`'],
  ['`video_safe_zone_violations_total`', 'counter', '—'],
  ['`video_duration_seconds`', 'histogram', '`language`'],
  ['`video_loudness_lufs`', 'histogram', '—'],
  ['`video_file_size_bytes`', 'histogram', '—'],
  ['`video_running_jobs`, `video_queued_jobs`', 'gauge', '—'],
  ['`video_http_requests_total`, `video_http_request_duration_seconds`', 'counter, histogram', '`route`, `method`, `status`'],
  ['`video_core_callback_failures_total`', 'counter', '`kind`'],
], [2.6, 1.2, 2.6]],
['ul', [
  'Logs: JSON lines with `ts`, `level`, `msg`, `service=video`, `production_id`, `job_id`, `run_id`, `step`, `trace_id`, `span_id`; agent transcripts are not logged, only stored as artifacts.',
  'Traces: span `video.job` (root continues the core\'s `traceparent`), child spans per step, `agent.run`, `sandbox.exec` (per command), `render.chunk`, `s3.upload`, `core.callback`. Attribute `production_id` on every span.',
  'Dashboards: steps timeline, cost per job, blocked reasons, check failures; alert rules: job cost > budget, render s/s > 3, blocked rate > 30 % per week.',
]],
['h1', '9. Security'],
['ul', [
  '**Secrets**: the Claude credential (`agent.auth.credential_ref`; kind `claude_oauth_token` in subscription mode, `anthropic_api_key` in api_key mode) is fetched per job (`GET /internal/v1/credentials/{ref}`, access: job), held in memory, given only to the agent container env as the one variable of its mode; never written to disk or logs. The structlog redaction processor masks keys matching `*key*`, `*token*`, `*oauth*`, `authorization` and the exact value of the credential (value scrubbing over every log line and transcript before upload).',
  '**Least privilege per step**: tools allowlist, no `Bash`, read-only inputs, network allowlist through the proxy, no Docker access for agents (DV1, DV2).',
  '**Prompt injection**: web pages, source comments, command output are files in `/in` or `/src` and are described as data in every `CLAUDE.md`; the agent cannot act outside its tools anyway; outputs are schema-validated.',
  '**Docker socket**: only through `docker-socket-proxy` with `CONTAINERS=1, EXEC=1, IMAGES=1, NETWORKS=1, VOLUMES=1, POST=1`, everything else 0; container templates are code-reviewed and unit-tested to have no binds, no privileged, no host network (NFR-VID-009).',
  '**Sandbox**: no network, limits, caps dropped, removed after use.',
  '**API**: bearer token comparison in constant time; admin endpoints require the same core token (calls are proxied by admin-api through core) — see 04 §3.4.',
  '**Supply chain**: images by digest, fonts and ffmpeg by sha256, Python dependencies locked with hashes (`uv lock`).',
]],
['h1', '10. Testing strategy'],
['table', ['Level', 'What', 'Tools'], [
  ['Unit', 'timing formulas (property tests), resolve, expect, cues, safe-zone transform, glyph check, validators and rules, input hashing, budget', 'pytest, hypothesis'],
  ['Renderer regression', 'the reference scenario renders; scene and step durations equal the reference within 3 %; key frames compared to approved PNGs (SSIM ≥ 0.98 against the module\'s own approved frames)', 'pytest + numpy'],
  ['Contract', 'core contract suite against the module API; JSON Schemas in `/info`', 'schemathesis, core fixtures'],
  ['Integration', 'full job with a fake agent runner (replays recorded outputs) + real sandbox + real render + MinIO + PostgreSQL', 'testcontainers'],
  ['Prompt (golden)', 'real Claude on the golden set before activating a prompt/model version', '`POST /admin/v1/golden`'],
  ['Security', 'container template tests, egress denial test, secret grep over artifacts', 'pytest'],
  ['E2E', 'core + module-video in Compose with the fake runner: idea → result callback', 'docker compose'],
], [1.2, 3.8, 1.4]],
['h1', '11. Deployment'],
['code', `# compose excerpt
module-video:
  image: ghcr.io/t1menar/manufacture/module-video@sha256:...
  environment: [VIDEO_DATABASE_URL, VIDEO_LISTEN_ADDR, MODULE_CORE_URL, MODULE_CORE_TOKEN,
                S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, DOCKER_HOST, VIDEO_AGENT_NETWORK,
                OTEL_EXPORTER_OTLP_ENDPOINT]
  networks: [internal, video-agents]
  cpus: 8
  mem_limit: 8g
  volumes: [video-work:/var/lib/module-video]     # run workspaces, render chunks
  healthcheck: {test: ["CMD", "curl", "-fsS", "http://localhost:8080/health"], interval: 10s}
video-docker-proxy:
  image: tecnativa/docker-socket-proxy@sha256:...
  environment: {CONTAINERS: 1, EXEC: 1, IMAGES: 1, NETWORKS: 1, VOLUMES: 1, POST: 1}
  volumes: [/var/run/docker.sock:/var/run/docker.sock:ro]
  networks: [internal]
networks:
  video-agents: {internal: true}`],
['ul', [
  'Dockerfile (module): `python:3.12-slim` by digest; ffmpeg static build by sha256; fonts by sha256; `uv sync --frozen`; non-root user; `ENTRYPOINT ["mvideo"]`.',
  'Agent image: `python:3.12-slim` + Node LTS (for Claude Code CLI if the SDK needs it; verify), `claude-agent-sdk` pinned, git, ripgrep; built and pushed with the module; digest written into settings by the admin.',
  '`/health`: process alive and DB reachable. `/ready`: DB, S3, Docker proxy, agent image present, fonts present, ffmpeg runnable, running jobs < `runtime.max_parallel_jobs`, and `auth: configured|missing` (credential reference set and fetchable). A usage or rate limit never makes the module not ready.',
]],
['h1', '12. Local development'],
['ul', [
  '`make dev`: Compose with PostgreSQL, MinIO, docker-socket-proxy, a fake core (records callbacks) and the module with reload.',
  '`mvrender render reference/create_database/ --out /tmp/cd.mp4 --workers 4` renders the reference without any agent; `mvrender preview … --at 12 40.5` writes PNG stills with the safe-zone overlay.',
  '`mvideo validate script path.json --research … --capture …` runs the same validator the agents use.',
  '`MVIDEO_FAKE_AGENT=replay:<dir>` replaces agent containers with recorded outputs, so the whole pipeline runs offline and free.',
]],
  ],
};
