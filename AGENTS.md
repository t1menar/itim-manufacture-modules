# itim-manufacture-modules — agent context (read this first)

Repo `github.com/t1menar/itim-manufacture-modules` (branch `main`). This is a **modules-only**
repository: the video pipeline modules for the iTim channel (idea → researched script → recorded
sandbox session → rendered 1080×1920 video → Telegram human review → Instagram Reels).

The original monorepo (Go core, admin-api, admin-panel and the full local stack) is preserved at
tag [`v1-legacy`](https://github.com/t1menar/itim-manufacture-modules/tree/v1-legacy). The new
Manufacture core lives in [`manufacture-core`](https://github.com/t1menar/manufacture-core);
the Python SDK and examples are in [`manufacture-sdk-python`](https://github.com/t1menar/manufacture-sdk-python)
and [`manufacture-examples`](https://github.com/t1menar/manufacture-examples).

Each remaining folder has a `CONTEXT.md` with the deep context of that module. Read this file, then
only the module(s) you touch. `docs/STATUS.md` holds decisions that still apply to the modules.

## Map

| Folder | Lang | Role |
|---|---|---|
| `modules/module-idea/` | Python | New pipeline, stage `idea`: idea backlog, playlists, rubrics, scheduling, cost and outcomes. See `docs/PIPELINE.md`. |
| `modules/module-scenario/` | Python | New pipeline, stage `scenario`: research (verified facts, knowledge cache) and the scenario in one module. See `docs/PIPELINE.md`. |
| `modules/module-video-generation/` | Python | New pipeline, stage `video`: capture (planner + sandbox runner behind Protocols), deterministic render/package on `mvrender`; palette, limits and design notes come from the idea. |
| `modules/module-instagram-publisher/` | Python | New pipeline, stage `publish`: Graph API Reels client, ledger (no double posts, reconcile on unknown), confirm hook before the irreversible call. |
| `modules/module-telegram-review/` | Python | New pipeline, stage `review`: two Telegram gates (script, finished post), approve/reject, comment after reject, round cap, decisions to the platform at-least-once. |
| `modules/module-video/` | Python | Stage `video` (module id `video-claude`): ideas DB + scheduler, Claude agent steps, sandbox capture, ffmpeg render (`mvrender`). |
| `modules/module-review/` | Python | Stage `review` (`review-telegram`): Telegram bot, approve/reject cards, publish notifications. |
| `modules/module-publish/` | Python | Stage `publish` (`publish-instagram`): Instagram Reels via Graph API, accounts, publish ledger. |
| `packages/mvrender/` | Python | Standalone renderer and timing library for `manufacture.scenario/1`; used by module-scenario (validation) and module-video-generation. |
| `packages/mf-storage/` | Python | Shared S3/MinIO helpers (s3:// parsing, presign) for review and publish. |
| `deploy/` | compose | Standalone MinIO for local module tests (`compose.minio.yml`, `scripts/mfinfra-minio.sh`). |
| `docs/` | md | `STATUS.md` (module decisions), `CONTENT.md` (content strategy), `REVIEW.md` (open findings). |

Each module lives in `modules/<module_name>/` (formerly `video-modules/`, renamed). The previous `core/`, `admin-api/` and `admin-panel/` trees are gone from `main`; recover them from `v1-legacy` or work in the new core repositories instead.

## How the modules fit together

These modules were built to talk to the legacy core over HTTP callbacks
`POST /internal/v1/jobs/{id}/progress|result|fail` with `Authorization: Bearer mft_…` and a
required `X-Fence` header; the core talked to modules over AMQP commands and HTTP. Delivery is
at-least-once with idempotent consumers (inbox tables, transactional outbox).

```
video DB idea (queued)
  → module-video scheduler writes idea.ready to its outbox
  → RabbitMQ exchange manufacture.events (routing key idea.ready)
  → core (legacy, or the new manufacture-core once modules are ported): production + job
  → job.requested → queue module.<module-id>.commands  (also HTTP POST /v1/jobs on the module)
  → video steps: analysis → research → script → capture → render → package → result callback
  → review job: Telegram card (sendVideo) → Approve | Reject(+reason → revise loop)
  → approval creates a publish intent → publish job → Instagram → permalink
  → notify.requested → Telegram "what was published where"
```

The new core is not compatible with these modules until they are ported onto the SDK. Until then,
an end-to-end video pipeline on `main` is not expected to run.

`modules/module-video/tests/test_core_contract.py` looks for `core/schemas/` next to the
module and **skips** when that tree is absent.

## Commands

```bash
# Python modules (uv):
cd modules/module-video && uv sync && make check   # ruff, mypy, import-linter, pytest
cd modules/module-review && uv sync && make check
cd modules/module-publish && uv sync && make check

# Single test:
cd modules/module-<x> && uv run pytest tests/path/test_file.py::test_name

# Shared S3 helpers:
cd packages/mf-storage && uv sync && uv run pytest

# Standalone MinIO (API 127.0.0.1:59000, console 59001):
docker compose -f deploy/compose.minio.yml up -d
# or: ./deploy/scripts/mfinfra-minio.sh
```

Build review/publish images from the repository root (Dockerfiles copy `packages/mf-storage`):

```bash
docker build -f modules/module-review/Dockerfile -t module-review:local .
docker build -f modules/module-publish/Dockerfile -t module-publish:local .
```

`make check` differs per module: video = lint+mypy+import-linter+test, review = lint+mypy+test, publish = lint+test (`check-strict` adds mypy).

CI lives in `.github/workflows/module-*.yml`, `mf-storage.yml` and `deploy-shell.yml`. Workflows
are path-filtered. Local module ports from the legacy stack (for reading older docs): video 58081,
review 58082, publish 58083; MinIO in this repo is 59000/59001.

## Standing rules (from the owner)

- Commit straight to `main` is allowed when the owner says so; **never add Claude/Co-Authored-By trailers** to commits or PRs.
- **Never print, paste or log secrets** (tokens, keys, passwords, `deploy/.env` contents, DB token columns). Do not read secret columns even for debugging. Tell the owner to rotate anything they paste in chat.
- Video content is **English**; fix problems in code, not by adding instructions to prompts. Answer the owner in **Russian**.
- Downloads of files, outward-facing or irreversible actions (publishing, deleting remote data) need explicit confirmation.
- Prefer dedicated tools; zsh on macOS: `sed -i ''`, watch `echo ==` expansions.
- Do not "fix" known-red CI in the modules (`module-video` mypy on `diagram.py`, `module-publish` ruff) unless the owner asks: the owner writes the modules.

## Cross-cutting gotchas (learned the hard way)

1. **module-video step cache** (`steps.input_hash` = step name/version/model/`settings_keys` subset/input/idea/upstream sha256/prompts). Changing `DEFAULT_PALETTE`, a step's `settings_keys` or a prompt invalidates hashes and re-spends money (one slip cost ~$7). Re-key trick: update `steps.input_hash` in the DB. Do not put render-only settings in the `script` step keys.
2. **Palette tokens** (`win_accent`, `accent_top`, `flow_light`, `sql_kw`, …) must exist in both `mvrender/palette.py DEFAULTS` and `mvideo/settings_model.DEFAULT_PALETTE`; brand overrides live in `mvideo/brand.py`.
3. **Render workers must share `reading_wps`** with the parent context (`_init_worker`), otherwise picture runs ahead of sound. `RenderStep.version` is bumped when output changes.
4. **Loudness** target −16 LUFS, closed loop around the AAC-encoded file in `mux_final` (AAC loses ≈1 LU and overshoots true peak by up to ≈3 dB; ceiling relaxed accordingly).
5. **Instagram/Meta**: system-user tokens (`EAA…`) need Graph base `https://graph.facebook.com`, API `v27.0`; IG business account id lives in `platform_accounts.external_id`. `rupload.facebook.com` accepts only ≈1.7 MB per request (no chunking) → default production path is **`url` upload mode via an SFTP video host** (file copied to a public HTTPS folder, cover too as `cover_url`, cron cleans files after 180 min). Caption is cut to 500 chars and ≤8 hashtags (`shorten_caption`).
6. **publish_ledger** prevents double posts. Switching fake → real requires deleting stale fake ledger rows. `media_publish` is never retried on 5xx; unknown outcome → reconcile → `unknown`.
7. Each module owns its own database (`video`, `review`, `publish`) and Alembic migrations.

## Where things are not finished

- These modules still speak the legacy core protocol. Porting them onto the new SDK is future work; do not start it unless the owner asks.
- `modules/module-video/uv.lock` predates the OpenTelemetry deps; `agent/prices.json` has placeholder prices.
- Not implemented in module-video: `/admin/v1/runs`, `/admin/v1/golden`, janitor for old artifacts.
