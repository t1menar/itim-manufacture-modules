# Code review notes (2026-11-10)

Scope today: the modules in this repository (`module-video`, `module-review`, `module-publish`)
and `packages/mf-storage`. Findings that applied only to the removed Go core and admin-api are
kept on tag `v1-legacy`.

## Fixed in an earlier pass (still true)

- `module-video/storage.put_file`: the sha256 of a finished video was computed on the event loop; now in a thread (`_hash_file`).
- Removed the Word-spec tooling and its dead references (`specgen`, `extract_prompts.js`, verbatim-prompt test, CI step).

## Checked and fine

- Blocking work in module-video (ffmpeg, sandbox exec, render) runs through `asyncio.to_thread`; publish uses `httpx.AsyncClient` and an async `sftp` subprocess.

## Open findings (not fixed; ordered by value)

1. **No retention anywhere.** `amqp_inbox` (all Python modules), `idea_outbox` and old artifacts in MinIO grow forever. Add a periodic purge (e.g. sent outbox/inbox older than 30 days) and a MinIO janitor (module-video janitor is also listed as not implemented).
2. **SFTP host key is not pinned** (`video_host.py` uses `StrictHostKeyChecking=accept-new` with a throw-away `known_hosts`): a MITM could intercept the uploaded public video (the key is not leaked). Pin the server key through a setting (`PUBLISH_VIDEO_HOST_KNOWN_HOSTS`).
3. **Whole video read into memory** in publish/review (`get_bytes`) — fine for ≈10–20 MB reels, but stream to the temp file for anything larger.
4. **Broad `except Exception`** (≈50 places in the Python modules). Most re-raise or log; audit the ones that swallow, especially in workers' loops, so a failing loop is visible in metrics.
5. **`uv.lock` of module-video is stale** (OpenTelemetry deps), tracing stays a no-op until `uv lock`. `agent/prices.json` has placeholder prices, so `usd` cost mode is inaccurate.
6. **Secrets at rest in plain text** in module DBs (`module_secrets`, `platform_accounts.access_token`, `credentials`) — acceptable for a single-owner local stack; encrypt before any shared deployment.
