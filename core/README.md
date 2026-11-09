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
- **No duplicates at DB level**: one running production per idea (`productions_live_uq`), unique `(idea_id, run_no)`,
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

## Not implemented yet (next slices)

- Internal HTTP API (callbacks, module reads, admin-facing endpoints) — routes return 501.
- Job status `dispatched` on confirm, timeouts/deadline sweeper, cancel/notify commands, revise loop for review.
- Settings table (scheduler limits are struct fields with spec defaults), module registry/heartbeats, credentials vault
  (`CORE_MASTER_KEY` is only validated), prompt versions, publication records, metrics/tracing.
- Python modules and the admin API.
