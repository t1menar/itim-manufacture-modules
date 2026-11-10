# Manufacture — agent context (read this first)

Monorepo `github.com/t1menar/manufacture` (branch `main`). An automated factory for short English
tech videos ("iTim" channel): idea → researched script → real recorded terminal/database session →
rendered 1080×1920 video → Telegram human review → Instagram Reels.

Each folder has a `CONTEXT.md` with the deep context of that module. Read the root file, then only the
module(s) you touch. `docs/STATUS.md` holds decisions (D18–D24) and merged-PR history.

## Map

| Folder | Lang | Role |
|---|---|---|
| `core/` | Go | Pipeline engine + module registry. Productions → variants → jobs, outbox/inbox over RabbitMQ, fencing, retries, publish intents. Being extracted into a standalone "pipeline router" project (SDK for modules planned). |
| `video-modules/module-video/` | Python | Stage `video` (module id `video-claude`): ideas DB + scheduler, Claude agent steps, sandbox capture, ffmpeg render (`mvrender`). |
| `video-modules/module-review/` | Python | Stage `review` (`review-telegram`): Telegram bot, approve/reject cards, publish notifications. |
| `video-modules/module-publish/` | Python | Stage `publish` (`publish-instagram`): Instagram Reels via Graph API, accounts, publish ledger. |
| `admin-api/` | Go | Localhost-only gateway for the panel (no login), proxies core + modules, audit log. |
| `admin-panel/` | TS/React | Russian-language SPA served by admin-api at `http://127.0.0.1:58084/`. |
| `contracts/` | JSON Schema | Shared idea/topic/event schemas (vendored into module-video; a test fails on drift). |
| `packages/mf-storage/` | Python | Shared S3/MinIO helpers (s3:// parsing, presign) for review and publish. |
| `deploy/` | shell/compose | One-command local stack (`./deploy/up.sh`), helper scripts. |
| `create-database-video/` | Python | Original hand-made reference video (the visual/scenario reference for the renderer). Not part of the runtime. |
| `docs/` | md | `STATUS.md` (decisions, history). Specs formerly kept as Word files were deleted; the code and `CONTEXT.md` files are the source of truth. |

## End-to-end flow

```
video DB idea (queued)
  → module-video scheduler (VIDEO_IDEAS_*: tick, max_in_flight, interval) writes idea.ready to its outbox
  → RabbitMQ exchange manufacture.events (routing key idea.ready)
  → core: production + variant + first job (parked in pending_ideas when max_concurrent_productions is hit)
  → job.requested → queue module.<module-id>.commands  (also HTTP POST /v1/jobs on the module)
  → video steps: analysis → research → script → capture → render → package → result callback
  → review job: Telegram card (sendVideo) → Approve | Reject(+reason → revise loop, review.max_rounds)
  → approval creates publish intent generation 1 → publish job → Instagram → permalink
  → notify.requested → Telegram "what was published where"
```

Modules talk to core over HTTP callbacks `POST /internal/v1/jobs/{id}/progress|result|fail` with
`Authorization: Bearer mft_…` and a required `X-Fence` header; core talks to modules over AMQP commands
and HTTP. Delivery is at-least-once with idempotent consumers (inbox tables, transactional outbox).

## Commands

```bash
./deploy/up.sh [--verbose]      # whole local stack (needs Docker + Compose v2); status.sh, logs.sh <svc>, down.sh
# Go is NOT installed on the host. Run Go in Docker:
docker run --rm -v $PWD:/src -v mf-gomod:/go/pkg/mod -w /src/core golang:1.26-bookworm go test ./...
# Python modules (uv): cd module-<x> && uv sync && make check   (ruff, mypy, import-linter, pytest)
# Panel: cd admin-panel && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

Integration tests need Docker (testcontainers) or `MF_TEST_DATABASE_URL` / `MF_TEST_AMQP_URL` for core.
CI lives in `.github/workflows/<module>.yml`. Local ports: core 58080, video 58081, review 58082,
publish 58083, admin 58084 (loopback only), PG 56432, AMQP 56672/UI 56673, MinIO 56000/56001.

## Standing rules (from the owner)

- Commit straight to `main` is allowed when the owner says so; **never add Claude/Co-Authored-By trailers** to commits or PRs.
- **Never print, paste or log secrets** (tokens, keys, passwords, `deploy/.env` contents, DB token columns). Do not read secret columns even for debugging. Tell the owner to rotate anything they paste in chat.
- Video content is **English**; fix problems in code, not by adding instructions to prompts. Answer the owner in **Russian**.
- Downloads of files, outward-facing or irreversible actions (publishing, deleting remote data) need explicit confirmation.
- Prefer dedicated tools; zsh on macOS: `sed -i ''`, watch `echo ==` expansions.

## Cross-cutting gotchas (learned the hard way)

1. **module-video step cache** (`steps.input_hash` = step name/version/model/`settings_keys` subset/input/idea/upstream sha256/prompts). Changing `DEFAULT_PALETTE`, a step's `settings_keys` or a prompt invalidates hashes and re-spends money (one slip cost ~$7). Re-key trick: update `steps.input_hash` in the DB. Do not put render-only settings in the `script` step keys.
2. **Palette tokens** (`win_accent`, `accent_top`, `flow_light`, `sql_kw`, …) must exist in both `mvrender/palette.py DEFAULTS` and `mvideo/settings_model.DEFAULT_PALETTE`; brand overrides live in `mvideo/brand.py`.
3. **Render workers must share `reading_wps`** with the parent context (`_init_worker`), otherwise picture runs ahead of sound. `RenderStep.version` is bumped when output changes.
4. **Loudness** target −16 LUFS, closed loop around the AAC-encoded file in `mux_final` (AAC loses ≈1 LU and overshoots true peak by up to ≈3 dB; ceiling relaxed accordingly).
5. **Instagram/Meta**: system-user tokens (`EAA…`) need Graph base `https://graph.facebook.com`, API `v27.0`; IG business account id lives in `platform_accounts.external_id`. `rupload.facebook.com` accepts only ≈1.7 MB per request (no chunking) → default production path is **`url` upload mode via an SFTP video host** (file copied to a public HTTPS folder, cover too as `cover_url`, cron cleans files after 180 min). Caption is cut to 500 chars and ≤8 hashtags (`shorten_caption`).
6. **publish_ledger** prevents double posts. Switching fake → real requires deleting stale fake ledger rows. `media_publish` is never retried on 5xx; unknown outcome → reconcile → `unknown` (core sets `needs_attention`).
7. **Core concurrency**: `system_settings.scheduler.max_concurrent_productions` (core DB, owner `core`, `is_current`). Extra `idea.ready` is parked in `pending_ideas`; module-video also caps `max_in_flight` (3) and `min_interval_s`.
8. **Republish** (`POST /api/v1/publish-intents/{id}/republish` `{reason, base_generation}`) builds a job from the latest content revision, upstream and module settings (`engine/republish.go`). Retried publish jobs must carry the open `intents`.
9. DB hosts the `core` migrations (goose) and the Python modules' Alembic migrations; each module owns its own database (`core`, `video`, `review`, `publish`, `admin`).

## Where things are not finished

- Core is being separated; module SDK is the owner's current work — avoid large core refactors without asking.
- `video-modules/module-video/uv.lock` predates the OpenTelemetry deps; `agent/prices.json` has placeholder prices.
- Core/publish state of the first real test publication (intent gen 15 `unknown`, variant `needs_attention`) was not reconciled (test posts, to be deleted by the owner).
- Not implemented: `/admin/v1/runs`, `/admin/v1/golden`, janitor for old artifacts in module-video; admin ideas/topics routes (`admin-api/docs/VIDEO_ADMIN_ROUTES.md`).
