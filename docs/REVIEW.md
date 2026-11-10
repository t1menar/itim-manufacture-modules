# Code review notes (2026-11-10)

Scope: core, admin-api, module-video, module-review, module-publish. Method: targeted read of the hot paths (callbacks, relay,
step runner, render, publish flow) plus grep sweeps for blocking calls inside async code, SQL built from strings, HTTP timeouts and body limits, indexes and retention.

## Fixed in this pass
- `module-video/storage.put_file`: the sha256 of a finished video was computed on the event loop; now in a thread (`_hash_file`).
- Removed the Word-spec tooling and its dead references (`specgen`, `extract_prompts.js`, verbatim-prompt test, CI step); `contractcheck` moved to `core/tools/contractcheck`.

## Checked and fine
- Go servers set Read/Write/Idle timeouts; request bodies are capped (`MaxBytesReader` / `LimitReader`); upstream client has a timeout.
- No SQL built from user input (only constant table names); jobs/variants lookups are covered by their unique indexes; outbox/pending queues have partial indexes.
- Blocking work in module-video (ffmpeg, sandbox exec, render) runs through `asyncio.to_thread`; publish uses `httpx.AsyncClient` and an async `sftp` subprocess.

## Open findings (not fixed; ordered by value)
1. **No retention anywhere.** `outbox` (sent rows), `inbox`, `events`, `idempotency_keys` (core), `amqp_inbox` (all Python modules), `idea_outbox` and old artifacts in MinIO grow forever. Add a periodic purge (e.g. sent outbox/inbox older than 30 days) and a MinIO janitor (module-video janitor is also listed as not implemented).
2. **SFTP host key is not pinned** (`video_host.py` uses `StrictHostKeyChecking=accept-new` with a throw-away `known_hosts`): a MITM could intercept the uploaded public video (the key is not leaked). Pin the server key through a setting (`PUBLISH_VIDEO_HOST_KNOWN_HOSTS`).
3. **Whole video read into memory** in publish/review (`get_bytes`) — fine for ≈10–20 MB reels, but stream to the temp file for anything larger.
4. **Broad `except Exception`** (≈50 places in the Python modules). Most re-raise or log; audit the ones that swallow, especially in workers' loops, so a failing loop is visible in metrics.
5. **`uv.lock` of module-video is stale** (OpenTelemetry deps), tracing stays a no-op until `uv lock`. `agent/prices.json` has placeholder prices, so `usd` cost mode is inaccurate.
6. **Admin-api has no auth by design** (D24): safe only while bound to loopback. If the port is ever published beyond localhost, add auth first.
7. **Secrets at rest in plain text** in module DBs (`module_secrets`, `platform_accounts.access_token`, `credentials`) — acceptable for a single-owner local stack; use core's AES-GCM vault before any shared deployment.
8. **Test-publication state** in core (intent generation 15 `unknown`, variant `needs_attention`) was never reconciled; harmless, but clean it if the DB is reused.
