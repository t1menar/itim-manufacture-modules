# module-review — context for agents

Python 3.12 / FastAPI / SQLAlchemy / aio-pika. Module id `review-telegram`. Telegram review bot; **review + publish notifications only** (D20/D24).
Admin slash commands are not routed (`admin/commands.py` and `clients/core_admin.py` are kept but unwired).

## Layout (`src/review/`)
`app.py` wiring, `bootstrap.py` (only env reader; 4 required vars `REVIEW_DATABASE_URL`, `REVIEW_LISTEN_ADDR`, `MODULE_CORE_URL`, `MODULE_CORE_TOKEN`),
`runtime_config.py` (DB-first config: `module_secrets`, `module_settings`, env only as fallback), `intake.py`, `api/` (`/v1/jobs`, `/v1/notify`,
`/admin/v1/secrets`, `/info` `/health` `/ready` `/metrics`), `jobs/` (`flow.py` review session state machine, `cards.py`, `worker.py` lease worker),
`notify/handler.py`, `telegram/` (`real.py` Bot API client with 429/5xx handling, `poller.py` long polling with offset in `bot_state`,
`fake.py` for tests, `sender.py`, `updates.py`), `admin/registration.py` (master-token registration), `storage/s3_client.py`, `workers/amqp_consumer.py`, `i18n/`.

## Behaviour
- A review job produces a card: multipart `sendVideo` read from MinIO (internal endpoint), inline Approve/Reject; >50 MB → link instead.
- Reject asks for a text reason (persisted `pending_reject`) → result `rejected` with `revise_target` → core runs a revise loop; revise cards reply to the previous card.
- Admin registration: master token generated on first start (`module_secrets telegram.master_token`, read via `deploy/scripts/review-master-token.sh`); the sender
  of the correct token in a private chat becomes the only admin; 5 failed attempts lock a user 15 min; `review-admin-reset.sh [--new-token]` hands the bot over.
  Fixed `telegram.admin_ids` disable registration. Jobs arriving before registration wait and are sent after it.
- Notify (`notify.requested`): "what was published where" as a reply to the approved card.
- Dedup: `amqp_inbox`, `telegram_updates_seen`. Secrets (`telegram.bot_token`) require a module restart; S3 keys are read per operation.

## Commands
```bash
cd module-review && uv sync && make check
uv run review migrate | serve
```
Tests never call api.telegram.org (respx). `REVIEW_TELEGRAM_MODE=fake|real` (Compose default real, DB setting `telegram.mode` wins).
Never print the bot token or master token.
