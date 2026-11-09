# module-publish

Stage `publish`: Instagram (and later platforms) publisher (Python 3.12). Module id `publish-instagram`.

Specification: `../docs/module-publish/`.

## Status

- **D23:** `platform_accounts` + local `publish_intents` + IG caption/hashtag limits live in this module (Alembic `0003`). Core keeps orchestration intent id/generation for admin republish; runner resolves accounts from the local registry when the job omits `platform_account_id`.
- **Job intake (this PR):** HTTP `/v1/jobs` + AMQP `job.requested` with inbox dedup; `runs` table + lease worker; FakeInstagramClient; progress/result/fail with `X-Fence`; cancel; unknown→reconcile (no blind resend). Structural content_revision checks (no real download/ffprobe yet).
- **Fake publish runner:** `publish.domain.run_publish_intents` + `FakeInstagramClient` builds contract-valid `stage-publish-output` / result callback bodies. HTTP job intake still 501 until phase 3.


- **Phase 1 (this PR):** project skeleton, bootstrap env, settings schema + holder, FastAPI `/info` `/health` `/ready` `/metrics`, problem+json, bearer auth on job/admin routes (handlers **501** until later), Alembic `0001` (`amqp_inbox`), optional AMQP consumer with inbox dedup, Core HTTP client (`X-Fence`, progress/result/fail), **fake Instagram Login client only** (no real network posts), Dockerfile, tests.
- Not yet: real Instagram Login OAuth, ledger reconcile beyond stub, multi-account parallel publish.

## Develop

```bash
uv sync
make check
# integration (optional): PUBLISH_TEST_DATABASE_URL=... PUBLISH_TEST_AMQP_URL=... uv run pytest
uv run publish migrate
uv run publish serve
```

Bootstrap env: `PUBLISH_DATABASE_URL`, `PUBLISH_LISTEN_ADDR`, `MODULE_CORE_URL`, `MODULE_CORE_TOKEN`. Optional: `PUBLISH_AMQP_URL`, `PUBLISH_AMQP_QUEUE`.

**No real Instagram or Telegram calls.** Publishing goes through `publish.instagram.fake.FakeInstagramClient` only.
