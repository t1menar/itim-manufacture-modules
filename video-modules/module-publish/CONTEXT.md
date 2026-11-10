# module-publish — context for agents

Python 3.12 / FastAPI / SQLAlchemy / aio-pika / `mf-storage`. Module id `publish-instagram`. Publishes Reels through the Instagram Graph API.

## Layout (`src/publish/`)
`app.py`, `bootstrap.py` (only env reader), `contract.py` (job modes `publish|retry|republish`), `intake.py`, `settings.py`, `api/` (`/v1/jobs`, `/admin/v1/accounts|secrets`),
`jobs/{service,worker,runner}.py` (runs table + lease worker), `domain/runner.py` (`run_publish_intents`: ledger, fence, reconcile), `instagram/`
(`base.py` interface, `fake.py`, `real.py` Graph client, `factory.py` wiring, `video_host.py` SFTP host, `errors.py` classification), `storage/artifacts.py`
(video/cover resolve, `shorten_caption`, `HASHTAGS_MAX`), `db/` (Alembic `0001…0006`), `clients/core.py`.

## Data
`platform_accounts` (external_id = IG business account id, access_token — never exposed by API), `publish_intents` (local mirror, D23), `publish_ledger`
(one row per intent+account: `publishing|published|failed|unknown`), `runs`, `module_secrets`, `module_settings`, `amqp_inbox`.

## Real publishing flow (`instagram/real.py`)
1. Resolve video: `url` mode (default in our deployment) copies the file from MinIO via SFTP to the video host and passes the public HTTPS URL; the cover goes the same way as `cover_url`.
   `direct` mode (resumable upload to rupload.facebook.com) only works for files ≲1.7 MB — do not use for real videos.
2. `POST /{ig_user}/media` (REELS, `video_url`, caption ≤500 chars/≤8 hashtags) → poll `status_code` until `FINISHED` → ledger arm (fence: run live, same fence, not cancelled, ≥30 s before deadline) → `POST media_publish` → permalink.
3. Never retry `media_publish` on 5xx/transport errors: reconcile (container status, recent media by caption/time) else `unknown` → core `needs_attention`.
- Config: `PUBLISH_INSTAGRAM_MODE` (fake|real), `…_GRAPH_BASE` (system-user `EAA…` tokens need `https://graph.facebook.com`; Instagram-Login tokens use `graph.instagram.com`), `…_API_VERSION` (v27.0),
  `…_UPLOAD_MODE` (url|direct), `PUBLISH_VIDEO_HOST`, `…_DIR`, `…_URL`, `…_KEY_B64` (base64 of the private key). The video host (`ziphy.ru`, user `reels`, sftp-only, Caddy HTTPS, cron cleanup >180 min) is an external server; its key is in `~/.ssh/manufacture_publish`, never in git.
- Switching fake→real: delete stale fake `publish_ledger` rows, set `PUBLISH_INSTAGRAM_MODE=real` in `deploy/.env`.

## Commands
```bash
cd module-publish && uv sync && make check     # needs mf_storage and minio importable (uv sync installs the local package)
uv run publish migrate | serve
```
Tests never call Meta (respx). Never print tokens or the key.
