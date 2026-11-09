# module-publish

Stage `publish`: Instagram (and later platforms) publisher (Python 3.12). Module id `publish-instagram`.

Specification: `../docs/module-publish/`.

## Status

- **D23:** `platform_accounts` + local `publish_intents` + IG caption/hashtag limits live in this module (Alembic `0003`). Core keeps orchestration intent id/generation for admin republish; runner resolves accounts from the local registry when the job omits `platform_account_id`.
- **Job intake (this PR):** HTTP `/v1/jobs` + AMQP `job.requested` with inbox dedup; `runs` table + lease worker; FakeInstagramClient; progress/result/fail with `X-Fence`; cancel; unknown→reconcile (no blind resend). Structural content_revision checks (no real download/ffprobe yet).
- **Fake publish runner:** `publish.domain.run_publish_intents` + `FakeInstagramClient` builds contract-valid `stage-publish-output` / result callback bodies. HTTP job intake still 501 until phase 3.


- **Phase 1 (this PR):** project skeleton, bootstrap env, settings schema + holder, FastAPI `/info` `/health` `/ready` `/metrics`, problem+json, bearer auth on job/admin routes (handlers **501** until later), Alembic `0001` (`amqp_inbox`), optional AMQP consumer with inbox dedup, Core HTTP client (`X-Fence`, progress/result/fail), **fake Instagram Login client only** (no real network posts), Dockerfile, tests.
- Not yet: real Instagram Login OAuth, ledger reconcile beyond stub, multi-account parallel publish.


## Secrets & settings (module DB first)

Migration `0004_module_secrets` adds `module_secrets` / `module_settings` and column `platform_accounts.access_token`.

**Priority:** DB wins; env is a **dev/test fallback**. Core credentials vault / `credential_ref` is **not** used for these secrets.

`GET /admin/v1/accounts` never returns `access_token`.

### SQL templates (placeholders only)

```sql
-- Per-account Instagram token + IG user id
UPDATE platform_accounts
SET
  external_id = '<IG_USER_ID>',
  access_token = '<INSTAGRAM_USER_ACCESS_TOKEN>',
  updated_at = now()
WHERE id = '<PLATFORM_ACCOUNT_UUID>';

-- Optional default token (used only if account.access_token empty)
INSERT INTO module_secrets (key, value) VALUES
  ('instagram.default_access_token', '<INSTAGRAM_USER_ACCESS_TOKEN>')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

-- MinIO/S3 keys (for MinIO/presigned PR)
INSERT INTO module_secrets (key, value) VALUES
  ('s3.access_key', '<MINIO_ACCESS_KEY>'),
  ('s3.secret_key', '<MINIO_SECRET_KEY>')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

INSERT INTO module_settings (key, value) VALUES
  ('s3', '{
     "endpoint": "127.0.0.1:59000",
     "public_endpoint": "127.0.0.1:59000",
     "bucket": "manufacture",
     "secure": false,
     "public_secure": false,
     "region": "us-east-1"
   }'::jsonb),
  ('instagram.mode', '"real"'::jsonb)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```

### Env fallback (optional)

| Env | Notes |
|-----|-------|
| `PUBLISH_INSTAGRAM_MODE` | `fake` or `real` |
| `PUBLISH_INSTAGRAM_ACCESS_TOKEN` | Fallback if account + default secret empty |
| `PUBLISH_INSTAGRAM_IG_USER_ID` | Fallback if `platform_accounts.external_id` empty |
| `PUBLISH_INSTAGRAM_GRAPH_BASE` | Default `https://graph.instagram.com` |
| `PUBLISH_INSTAGRAM_API_VERSION` | Default `v22.0` |

### Setup (operator)

1. Meta developer app + Instagram professional/Business account linked.
2. Permissions: `instagram_business_basic` + `instagram_business_content_publish` (Instagram Login) **or** `instagram_basic` + `instagram_content_publish`.
3. Seed `platform_accounts` with `external_id` = IG user id and `access_token` (SQL above).
4. **Public HTTPS `video_url`:** Graph downloads the file itself. `s3://` refs fail until MinIO (or equivalent) issues a presigned HTTPS URL.

### Behaviour

- Create container `POST /{ig-user-id}/media` with `media_type=REELS`, `video_url`, `caption`.
- Poll `GET /{container-id}?fields=status_code` until `FINISHED` (or `ERROR`/`EXPIRED`).
- `POST /{ig-user-id}/media_publish` with `creation_id`; then read `permalink`.
- Check `content_publishing_limit` (quota_usage / config.quota_total) — do not hardcode 50 vs 100.
- Unknown outcomes → reconcile by media/container id (**no blind resend**).
- Errors classified: rate-limit / 5xx retryable; auth & invalid request permanent.

**CI/tests never call graph.facebook.com / graph.instagram.com** — respx mocks a local Graph base.

## Develop

```bash
uv sync
make check
# integration (optional): PUBLISH_TEST_DATABASE_URL=... PUBLISH_TEST_AMQP_URL=... uv run pytest
uv run publish migrate
uv run publish serve
```

Bootstrap env: `PUBLISH_DATABASE_URL`, `PUBLISH_LISTEN_ADDR`, `MODULE_CORE_URL`, `MODULE_CORE_TOKEN`. Optional: `PUBLISH_AMQP_URL`, `PUBLISH_AMQP_QUEUE`.

**CI/tests never call Meta Graph hosts.** Set `PUBLISH_INSTAGRAM_MODE=real` only with a real token and public HTTPS video URLs.

## MinIO / presigned video URLs

Real Instagram publish resolves `s3://` artifact refs to a **public** presigned HTTPS `video_url` (SigV4 signed for `public_endpoint`, not the internal `minio:9000` host). Config from module DB (`s3.*`) with env fallback. Package: `packages/mf-storage`. Local default: `http://127.0.0.1:59000` via `deploy/compose.minio.yml`. For live Instagram, tunnel that port (cloudflared/ngrok) and set `public_endpoint` to the tunnel host — no permanent domain/TLS required.

**module-video** must upload the object to the same bucket/key; this module does not change video upload.
