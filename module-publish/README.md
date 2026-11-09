# module-publish

Stage `publish`: Instagram (and later platforms) publisher (Python 3.12). Module id `publish-instagram`.

Specification: `../docs/module-publish/`.

## Status

- **D23:** `platform_accounts` + local `publish_intents` + IG caption/hashtag limits live in this module (Alembic `0003`). Core keeps orchestration intent id/generation for admin republish; runner resolves accounts from the local registry when the job omits `platform_account_id`.
- **Job intake (this PR):** HTTP `/v1/jobs` + AMQP `job.requested` with inbox dedup; `runs` table + lease worker; FakeInstagramClient; progress/result/fail with `X-Fence`; cancel; unknown→reconcile (no blind resend). Structural content_revision checks (no real download/ffprobe yet).
- **Fake publish runner:** `publish.domain.run_publish_intents` + `FakeInstagramClient` builds contract-valid `stage-publish-output` / result callback bodies. HTTP job intake still 501 until phase 3.


- **Phase 1 (this PR):** project skeleton, bootstrap env, settings schema + holder, FastAPI `/info` `/health` `/ready` `/metrics`, problem+json, bearer auth on job/admin routes (handlers **501** until later), Alembic `0001` (`amqp_inbox`), optional AMQP consumer with inbox dedup, Core HTTP client (`X-Fence`, progress/result/fail), **fake Instagram Login client only** (no real network posts), Dockerfile, tests.
- Not yet: real Instagram Login OAuth, ledger reconcile beyond stub, multi-account parallel publish.


## Real Instagram Graph API (optional)

Default remains **fake** (tests/CI). Live Reels publishing:

| Env | Required | Notes |
|-----|----------|-------|
| `PUBLISH_INSTAGRAM_MODE` | no (default `fake`) | `fake` or `real` |
| `PUBLISH_INSTAGRAM_ACCESS_TOKEN` | when `real`* | Instagram User access token with `instagram_business_content_publish` (Instagram Login) or `instagram_content_publish` (Facebook Login). **Never commit/log.** |
| `PUBLISH_INSTAGRAM_ALLOW_VAULT_ONLY` | no | Set `1` to skip bootstrap token and resolve only via Core `cred:…` on each account |
| `PUBLISH_INSTAGRAM_IG_USER_ID` | optional | Default IG user id if `platform_accounts.external_id` empty |
| `PUBLISH_INSTAGRAM_GRAPH_BASE` | no | Default `https://graph.instagram.com` (Facebook Login host: `https://graph.facebook.com`) |
| `PUBLISH_INSTAGRAM_API_VERSION` | no | Default `v22.0` (override when Meta bumps) |

\* Or per-account `settings.credential_ref` / `access_token_ref` pointing at Core credentials vault (`GET /internal/v1/credentials/{ref}`).

### Setup (operator)

1. Meta developer app + Instagram professional/Business account linked.
2. Permissions: `instagram_business_basic` + `instagram_business_content_publish` (Instagram Login) **or** `instagram_basic` + `instagram_content_publish` (+ Page tokens for Facebook Login).
3. Seed `platform_accounts` with `external_id` = IG user id; store token in env or vault.
4. **Public HTTPS `video_url`:** Graph downloads the file itself. `s3://` refs fail until MinIO (or equivalent) issues a presigned HTTPS URL. This is an intentional blocker.

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
