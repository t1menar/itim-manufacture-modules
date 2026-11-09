# module-review

Stage `review`: Telegram review bot (Python 3.12). Module id `review-telegram`.

Specification: `../docs/module-review/` (`module-review-01-description.docx` … `module-review-06-prompts.docx`).

## Status

**D20 (updated):** bot does **review + publish notifications only** (no admin slash commands). Core admin HTTP (#11) stays for DB/ops; `MODULE_CORE_ADMIN_TOKEN` remains env-only if the client is used offline.

**D20 legacy note:** core admin token is **only** bootstrap env `MODULE_CORE_ADMIN_TOKEN` (`mfa_…`). Do **not** store it as a Core credentials ref. Allowlist: `REVIEW_ADMIN_TELEGRAM_IDS`. Actor header: `X-Admin-Actor: tg:<telegram_user_id>`.



- **CoreAdminClient** library kept (not wired into bot updates). Admin slash commands are not routed.

- **Phase 1 (this PR):** project skeleton, bootstrap env (exactly four required vars), settings schema + holder, FastAPI `/info` `/health` `/ready` `/metrics`, problem+json, bearer auth on job/admin routes (handlers return **501 not_implemented** until later phases — no fake success), Alembic migration `0001` (`amqp_inbox`, `bot_state`), optional AMQP consumer with inbox dedup when `REVIEW_AMQP_URL` is set, Core HTTP client stub (progress/result/fail with `X-Fence`, heartbeat, settings, credentials), Dockerfile, CI.
- **Job intake (this PR):** HTTP/AMQP accept, review sessions in DB, FakeTelegram `sendVideo` card with Approve/Reject; reject asks for a text reason (persisted `pending_reject`); revise versions reply to the previous card; publish notify replies to the approved card. Admin slash commands are **not** routed.
- **Notify:** `NotifyHandler` consumes `notify.requested` (HTTP `/v1/notify` + AMQP) with inbox dedup; formats admin text; sends via `MessageSender` (`FakeTelegramBot` in tests — no real Telegram).
- Real Telegram long-polling: implemented behind `REVIEW_TELEGRAM_MODE=real`. Still not: Anthropic; rich reviewer directory UI.


## Secrets & settings (module DB first)

Migration `0004_module_secrets` adds:

| Table | Purpose |
|-------|---------|
| `module_secrets` | Secret strings (`key` PK, `value` text). **Never log or return via API.** |
| `module_settings` | Non-secret JSON (`key` PK, `value` jsonb) |

**Priority:** DB row wins; env is a **dev/test fallback** only.

### SQL templates (fill placeholders yourself — do not commit real values)

```sql
-- Telegram bot token (from @BotFather)
INSERT INTO module_secrets (key, value) VALUES
  ('telegram.bot_token', '<TELEGRAM_BOT_TOKEN>')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

-- Mode + API base (optional; default fake / https://api.telegram.org)
INSERT INTO module_settings (key, value) VALUES
  ('telegram.mode', '"real"'::jsonb),
  ('telegram.api_base', '"https://api.telegram.org"'::jsonb),
  ('telegram.admin_ids', '{"ids": [<ADMIN_TG_USER_ID>, …]}'::jsonb),
  ('telegram.chat_ids', '{"ids": [<REVIEW_CHAT_ID>, …]}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

-- MinIO/S3 keys (used when MinIO/presigned PR is merged)
INSERT INTO module_secrets (key, value) VALUES
  ('s3.access_key', '<MINIO_ACCESS_KEY>'),
  ('s3.secret_key', '<MINIO_SECRET_KEY>')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();

INSERT INTO module_settings (key, value) VALUES
  ('s3', '{
     "endpoint": "<INTERNAL_HOST:PORT>",
     "public_endpoint": "<PUBLIC_TLS_HOST>",
     "bucket": "manufacture",
     "secure": false,
     "public_secure": true,
     "region": "us-east-1"
   }'::jsonb)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```

### Env fallback (optional)

| Env | Notes |
|-----|-------|
| `REVIEW_TELEGRAM_MODE` | `fake` or `real` (overridden by `module_settings.telegram.mode` when set) |
| `REVIEW_TELEGRAM_BOT_TOKEN` | Fallback if `module_secrets.telegram.bot_token` empty |
| `REVIEW_TELEGRAM_API_BASE` | Fallback API host |
| `REVIEW_ADMIN_TELEGRAM_IDS` | Comma-separated; fallback for `telegram.admin_ids` |
| `REVIEW_CHAT_IDS` | Fallback for `telegram.chat_ids` |

Behaviour in `real` mode:

- Long-poll `getUpdates` with offset in `bot_state`; each `update_id` claimed once in `telegram_updates_seen`.
- Review cards: `sendVideo` + inline **Одобрить / Отклонить**; `answerCallbackQuery`; reject → pending reason text; revise replies with `reply_to_message_id` + `allow_sending_without_reply`.
- Publish notify: «что и куда опубликовано» as reply to the card when possible.
- HTTP 429 honors `retry_after`; 5xx exponential backoff.
- Files over Bot API **50 MB** (or URL fetch failures for large media) → message with a link instead of `sendVideo`.

**No real calls in CI/tests** — unit tests mock the API base with respx.

## Develop

```bash
uv sync
make check
# integration (optional): REVIEW_TEST_DATABASE_URL=... REVIEW_TEST_AMQP_URL=... uv run pytest
uv run review migrate
uv run review serve
```

Bootstrap env only: `REVIEW_DATABASE_URL`, `REVIEW_LISTEN_ADDR`, `MODULE_CORE_URL`, `MODULE_CORE_TOKEN`. Optional: `REVIEW_AMQP_URL`, `REVIEW_AMQP_QUEUE`. All other configuration is Core settings (04 §8).

**CI/tests never call api.telegram.org.** Set `REVIEW_TELEGRAM_MODE=real` only in a dedicated environment with a bot token.
