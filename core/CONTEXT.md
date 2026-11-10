# core — context for agents

Go service (`core/cmd/core`, subcommands `migrate`, `serve`). Pipeline engine + module registry. Postgres (goose
migrations `internal/db/migrations/0001…0012`), RabbitMQ (`internal/messaging`), HTTP (`internal/httpapi`).
Being extracted into a standalone "pipeline router"; modules will plug in through an SDK (owner's ongoing work).

## Domain model
`channel → pipeline (seed default-v1, 0002_seed.sql) → production (one per idea, `idea_ref`) → variants → jobs (chain, try, fence)`.
Opaque `idea_ref` / `idea_id` + `idea_rev`: ideas live in module-video (D21), core never stores their content.
Content revisions are immutable snapshots; **publish_intents** `(variant, platform_account, generation)` orchestrate
publishing and republishing; `pending_ideas` parks `idea.ready` under back-pressure (migration 0012).
`system_settings` is versioned (`base_version`→409, `If-Match`→412); `scheduler.max_concurrent_productions` lives there.

## Code map (`internal/`)
- `engine/` — state machine: `idea_ready.go` (intake, scheduler of parked ideas), `engine.go` (start production, `enqueueRequest`
  builds job requests incl. upstream via `loadJobUpstream` and open publish `intents`), `callbacks.go` (module callbacks:
  progress/result/fail, fencing, validation), `events.go` (inbox consumer handlers, `completeProduction`), `after_review_approved.go`,
  `after_publish.go` (intent aggregation → `published` / `needs_attention`), `republish.go`, `revision.go`.
- `messaging/` — `topology.go` (exchanges `manufacture.commands|events|dlx`, queues `core.job-events`, `module.<id>.commands`), `relay.go`
  (transactional outbox relay: lease + SKIP LOCKED + publisher confirms + backoff 1s…5min → `dead`), `consumer.go` (inbox,
  retry with growing delay, DLQ after MaxAttempts), `envelope.go`.
- `modules/` registry (register, token rotate, activate, heartbeat, offline sweeper). `credentials/` + `crypto/` AES-256-GCM vault (`CORE_MASTER_KEY`).
- `settings/`, `prompts/` (render helper only; core stores no prompts, D16), `schema/` (JSON Schema validation of results), `publish/`, `auth/`, `bootstrap/`, `db/`.
- `schemas/` (repo `core/schemas`) are the wire contracts: `job-request`, `result`, `fail`, `progress`, `notify`, `stage-*-output`, `events/*`. `api/openapi.yaml` is partial.

## Invariants (do not break)
- One running production per idea; one live job per variant / per production-scope stage; unique `(chain_id, try)`.
- Business row + outbox row commit in one transaction; `message_id` fixed at enqueue and reused on resend.
- Fence grows only on `Takeover`; old-fence/foreign-producer events are recorded `stale`/`conflict`.
- Job `deadline` set after outbox confirm; the sweeper creates retry tries on timeout (`try 2,3`).
- Unknown publish outcome → intent `unknown`, variant `needs_attention` (`publish_outcome_unknown`); never blind-resend.
- Completing an already finished production (republish) must not fail the result callback (`completeProduction` treats `ErrNoRows` as no-op).

## HTTP surface
Probes `/health`, `/ready`. Module callbacks (`Bearer mft_…`, `X-Fence`): `POST /internal/v1/jobs/{id}/progress|result|fail`,
`POST /internal/v1/modules/self/heartbeat`. Admin (`Bearer mfa_…`, `X-Admin-Actor`): modules register/activate, settings PUT,
`POST /internal/v1/publish-intents/{id}/republish`, productions/variants/jobs reads and cancel/retry/skip (used by admin-api).

## Commands
```bash
docker run --rm -v $PWD/..:/src -v mf-gomod:/go/pkg/mod -w /src/core golang:1.26-bookworm go test ./...   # no host Go
go run ./cmd/core migrate | serve        # inside the container or with Go installed; env in core/.env.example
MF_TEST_DATABASE_URL=… MF_TEST_AMQP_URL=… go test -race -count=1 ./...   # integration; each test makes its own DB/queue prefix
```
CI `.github/workflows/core.yml`: gofmt, vet, race tests on postgres:17 + rabbitmq:4, fails if an integration test skips.

## Gotchas
- RabbitMQ 4 does not count nack-requeue toward `x-delivery-limit`; the consumer counts attempts itself.
- Deploy image: `deploy/Dockerfile.core`; compose service `core`; admin token `CORE_ADMIN_TOKEN` (`mfa_…`) in `deploy/.env`.
- Spec Word documents were removed; schemas in `core/schemas` and the code are authoritative.
