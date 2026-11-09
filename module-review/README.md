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


## Real Telegram (optional)

Default remains **fake** (tests/CI). For a live bot:

| Env | Required | Notes |
|-----|----------|-------|
| `REVIEW_TELEGRAM_MODE` | no (default `fake`) | `fake` or `real` |
| `REVIEW_TELEGRAM_BOT_TOKEN` | when `real` | From [@BotFather](https://t.me/BotFather). **Never commit or log.** |
| `REVIEW_TELEGRAM_API_BASE` | no | Default `https://api.telegram.org` (override only for mocks) |
| `REVIEW_ADMIN_TELEGRAM_IDS` | recommended | Comma-separated Telegram user ids allowed to approve/reject |
| `REVIEW_CHAT_IDS` | optional | Chats that receive cards/notify (defaults to admin ids) |

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
