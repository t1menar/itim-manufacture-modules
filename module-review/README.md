# module-review

Stage `review`: Telegram review bot (Python 3.12). Module id `review-telegram`.

Specification: `../docs/module-review/` (`module-review-01-description.docx` … `module-review-06-prompts.docx`).

## Status

- **D20 admin (this PR):** `CoreAdminClient` (`mfa_` + `X-Admin-Actor: tg:<id>`), allowlist, command router, `FakeTelegramBot`. Optional bootstrap: `MODULE_CORE_ADMIN_TOKEN`, `REVIEW_ADMIN_TELEGRAM_IDS`.


- **Phase 1 (this PR):** project skeleton, bootstrap env (exactly four required vars), settings schema + holder, FastAPI `/info` `/health` `/ready` `/metrics`, problem+json, bearer auth on job/admin routes (handlers return **501 not_implemented** until later phases — no fake success), Alembic migration `0001` (`amqp_inbox`, `bot_state`), optional AMQP consumer with inbox dedup when `REVIEW_AMQP_URL` is set, Core HTTP client stub (progress/result/fail with `X-Fence`, heartbeat, settings, credentials), Dockerfile, CI.
- Not yet: data model for reviews/keys (phase 2), job intake (phase 3), Telegram bot (phase 4+), real notify/summary.

## Develop

```bash
uv sync
make check
# integration (optional): REVIEW_TEST_DATABASE_URL=... REVIEW_TEST_AMQP_URL=... uv run pytest
uv run review migrate
uv run review serve
```

Bootstrap env only: `REVIEW_DATABASE_URL`, `REVIEW_LISTEN_ADDR`, `MODULE_CORE_URL`, `MODULE_CORE_TOKEN`. Optional: `REVIEW_AMQP_URL`, `REVIEW_AMQP_QUEUE`. All other configuration is Core settings (04 §8).

**No real Telegram or Anthropic calls in this phase.**
