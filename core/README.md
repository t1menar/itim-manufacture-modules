# core

Pipeline engine and module registry (Go).

Specification: `../docs/core/` (`core-01-description.docx` ... `core-06-prompts.docx`; this slice implements parts of core-03, core-04 §15–17 and core-05).
This is the **foundation slice**; see "Not implemented yet" below.

## Run

```sh
cp .env.example .env    # fill in real values outside git
set -a; . ./.env; set +a
go run ./cmd/core migrate   # apply migrations and exit
go run ./cmd/core serve     # migrate, then HTTP probes + scheduler + outbox relay + event consumer
```

`SIGINT`/`SIGTERM` stop the HTTP server (15 s grace) and all loops; unacked messages return to the queue.

Probes: `GET /health` (process alive), `GET /ready` (503 with `{"checks":{"db":…,"broker":…}}` if a dependency is down).
Every other `/internal/…` route answers `501 not_implemented` (problem+json).

## What works

- **Migrations** (goose, Postgres session lock): domain tables, outbox, inbox, seed pipeline `default-v1`.
- **D21**: ideas live in module-video; core stores opaque `idea_ref` / `idea_id`+`idea_rev` only; intake via `idea.ready`.
- **No duplicates at DB level**: one running production per idea (`productions_live_uq`), unique `idea_ref`, unique `(idea_id, run_no)`,
  one live job per variant / per production-scope stage (`jobs_variant_live_uq`, `jobs_production_live_uq`),
  unique `(chain_id, try)`; scheduler serialised by an advisory xact lock + `SKIP LOCKED`.
- **Transactional outbox**: business rows and the outbox row commit in one transaction. The relay claims rows with a
  lease (`SKIP LOCKED`), publishes `mandatory` + persistent with publisher confirms, marks `sent` only after the ack;
  an unroutable return or nack is a failure with exponential backoff (1 s … 5 min) and `dead` after N attempts.
  `message_id` is fixed at enqueue and reused on every resend; an expired lease of a crashed relay is taken over.
- **Inbox consumer** (`core.job-events`): inbox row + state change in one transaction, ack only after commit,
  duplicates acked without effect, poison messages dead-lettered at once, handler errors requeued with a growing delay and
  dead-lettered to `.dlq` after `MaxAttempts` (counted by the consumer, since RabbitMQ 4 does not count
  nack-requeue toward `x-delivery-limit`; crash redeliveries are bounded by `x-delivery-limit` too).
- **Engine**: start production → variants → first job; job events `progress/succeeded/failed` advance the snapshot,
  retry transient failures in the same chain, `needs_attention` / `failed` otherwise; production/idea completion.
  Fence grows only on `Takeover`; events with an old fence or from a foreign producer are recorded `stale`/`conflict`.

Delivery is at-least-once with idempotent consumers. There is no exactly-once.

## Tests

```sh
go test ./...                    # unit tests; integration tests skip without the env below
MF_TEST_DATABASE_URL=postgres://postgres@localhost:5432/postgres \
MF_TEST_AMQP_URL=amqp://guest:guest@localhost:5672/ \
go test -race -count=1 ./...     # each test creates its own database and queue prefix
```

CI (`.github/workflows/core.yml`) runs gofmt, vet, and the race-enabled tests against `postgres:17` and `rabbitmq:4`
service containers and fails if an integration test is skipped.

## Publish intents / cancel / notify (this slice)

- **Content revisions** + **publish_intents** with unique `(variant_id, platform_account_id, generation)`.
  Generation 1 on approval; snapshot of `content_revision_id` is immutable. Admin republish (D18/C38): `POST /internal/v1/publish-intents/{id}/republish` with required reason + `base_generation`; no auto-republish.
- Unknown publish outcome → intent `unknown` + variant `needs_attention`/`publish_outcome_unknown` (reconcile first; never blind resend).
- **Cancel** enqueues one `job.cancel_requested` with a stable `message_id`; **notify** via `notify.requested` outbox.

## Registry / credentials / prompts (this slice)

- **Module registry:** `POST /internal/v1/modules` (admin, idempotent), token rotate, activate, `POST …/self/heartbeat`;
  offline sweeper marks `health=down` when `last_seen_at` is stale; dispatcher only assigns to `active AND health=up`.
- **Credentials:** AES-256-GCM (`CORE_MASTER_KEY`), random nonce, AAD=`ref||key_version`; module read with access checks; access log; secrets never logged.
- **Prompts:** core keeps **no** prompts table (D16/C40). Shared helper only: `internal/prompts` (`Render` / `{{var}}`, unknown variable → error, no eval).
  module-video owns storage, activation, audit and reports used versions in result `provenance.prompts` + optional `provenance.prompt_refs[]`.

## This slice also adds

- Module callbacks `POST /internal/v1/jobs/{id}/progress|result|fail` with Bearer `mft_...`, required `X-Fence`,
  inbox dedup, fencing and problem+json codes (`401`/`403`/`409 job_not_current|job_terminal`/`422 output_invalid`).
- Job status `dispatched` + `deadline` after outbox confirm; timeout sweeper (`SKIP LOCKED`, once under contention).
- Versioned `system_settings` (seeded core v1); `PUT /internal/v1/modules/core/settings` with `base_version`→409 and `If-Match`→412.
- Review loop: reject → revise on `revise_target` → new review round; after `review.max_rounds` → `needs_attention`/`max_rounds`.
- `CancelJob` → `cancelled` + `needs_attention`/`cancelled_by_admin`.

## Publish result + notify (this slice)

- Publish `result` callback: `publications[]` → intent `published` / `failed`(+`last_error.retryable`) / `unknown`; skipped → cancelled.
- Aggregate per variant → `published` (advance) or `needs_attention` (`publish_partial` / `publish_failed` / `publish_outcome_unknown`).
- `notify_stage` on the snapshot row → stable `notify.requested` outbox (`message_id = sha1(job_id||"notify")`) to the active review module.
- Publish `fail` (blocked / retries exhausted): open intents → `unknown`, variant `publish_outcome_unknown`, notify `failed`.

## Not implemented yet (next slices)

- Remaining module reads (§4): credentials, productions, artifacts presign — still 501.
- Admin-api surface (§2), module registration/heartbeats, credentials vault (`CORE_MASTER_KEY` validated only).
- Full JSON Schema validation of stage outputs (review checks are hand-coded: decision/reason).
- Notify/cancel AMQP commands to modules, prompt versions, publication records, metrics/tracing.
- Python modules and the admin API.
