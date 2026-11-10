module.exports = {
  dir: 'admin-api',
  file: 'admin-api-03-technical.docx',
  meta: {
    title: 'admin-api — Technical Design',
    subtitle: 'Stack, structure, data model, configuration, deployment, observability, security, testing',
    doc: 'admin-api-03-technical', version: '0.2', status: 'Draft', date: '2026-11-10',
  },
  blocks: [
['note', '**D24.** Login, sessions, TOTP, invitations, roles and a public TLS hostname are withdrawn. Access is localhost-only with a Host/Origin allowlist; see admin-api-01 v0.3. Implement the public surface listed there and in `admin-api/api/openapi.yaml`.'],
['h1', '1. Stack'],
['table', ['Area', 'Choice', 'Why'], [
  ['Language', 'Go 1.25 (minimum in `go.mod`; verify current stable at implementation time)', 'system decision D2; same toolchain as the core'],
  ['HTTP router', '`github.com/go-chi/chi/v5`', 'stdlib-compatible `http.Handler`, route templates for metrics labels, used by the core'],
  ['OpenAPI server code', '`github.com/oapi-codegen/oapi-codegen/v2` (chi strict server + models) and `github.com/getkin/kin-openapi` request validator middleware', 'design-first contract; validation from the same document'],
  ['Core client', 'oapi-codegen client generated from `core/api/openapi.yaml` (read at build time, not imported)', 'compile-time check against the core contract; monorepo rule: no code imports between services'],
  ['Database', 'PostgreSQL 17, database `admin`; `github.com/jackc/pgx/v5` (pgxpool); `sqlc` for typed queries; `github.com/pressly/goose/v3` migrations embedded with `embed.FS`', 'typed SQL without an ORM; same tools as the core'],
  ['Password hashing', '`golang.org/x/crypto/argon2` (`IDKey`), PHC string encoding written in-house (≈80 lines, tested)', 'standard library extension; no third-party crypto'],
  ['TOTP', 'RFC 6238 implemented in-house on `crypto/hmac` + `crypto/sha1` (≈60 lines) with RFC test vectors; `otpauth://` URI builder', 'tiny, auditable, and lets us control the replay rule (last accepted step)'],
  ['Encryption', '`crypto/aes` + `crypto/cipher` (AES-256-GCM), `golang.org/x/crypto/hkdf` for sub-keys', 'same primitives as core credentials'],
  ['Rate limiting', '`golang.org/x/time/rate` token buckets in memory, keyed by IP or user id, LRU-bounded', 'single instance in stage 1'],
  ['Observability', '`log/slog` JSON handler; `github.com/prometheus/client_golang`; OpenTelemetry Go SDK with `otelhttp` and `github.com/exaring/otelpgx`', 'system rule: Prometheus, Loki, OTel'],
  ['Testing', '`testing` + `github.com/stretchr/testify`, `github.com/testcontainers/testcontainers-go` (PostgreSQL 17), `net/http/httptest` fake core, k6 for load', 'real database in integration tests'],
  ['Lint and security', '`golangci-lint` (govet, staticcheck, errcheck, gosec, revive, bodyclose, sqlclosecheck), `govulncheck`', 'NFR-AAPI-005, -010'],
  ['TS client (in admin-panel)', '`openapi-typescript` (types) + `openapi-fetch` (runtime)', 'small, typed, no generated runtime code to review'],
  ['Reverse proxy', 'Caddy 2 (automatic HTTPS)', 'TLS and static files in one small config'],
], [1.2, 3.2, 2.4]],

['h1', '2. Repository layout'],
['code', `admin-api/
  cmd/admin-api/main.go        subcommands: serve | migrate | setup-token | healthcheck | version
  api/openapi.yaml             public API, source of truth (OpenAPI 3.0.3)
  api/oapi-codegen.yaml        server generation config
  api/core-client.yaml         client generation config, input ../core/api/openapi.yaml
  internal/
    bootstrap/                 env vars (5 + OTel), key ring from ADMIN_MASTER_KEY
    settings/                  embedded JSON Schema, refresher, cache table, typed accessors
    server/                    chi router, middleware chain, route table (permission, audit action, upstream)
    handlers/                  one file per group: auth.go users.go audit.go ideas.go ... implement StrictServerInterface
    gen/                       generated: api.gen.go (server + models), coreclient.gen.go  (do not edit)
    auth/                      argon2id PHC, password policy, common-password blocklist (embed), lockout
    totp/                      RFC 6238, recovery codes
    session/                   store, cookie, CSRF derivation, step-up
    authz/                     permissions, role matrix, start-up completeness check
    audit/                     intent/complete writer, masker, reconciler, retention
    upstream/                  core client wrapper: headers, timeouts, retries, error mapping, relay
    problem/                   RFC 9457 type, codes, writer
    ratelimit/                 IP and user buckets
    store/                     sqlc output + migrations/*.sql (goose)
    obs/                       metrics registry, slog setup, tracing
  db/queries/*.sql             sqlc input
  sqlc.yaml  Makefile  Dockerfile  .golangci.yml
  test/contract/  test/integration/  test/e2e/  test/load/`],
['h2', '2.1 Route table'],
['p', 'Each route is declared once in `internal/server/routes.go` with its permission, step-up flag, audit action and upstream timeout class. The generated OpenAPI handler interface is wrapped by middleware that reads this table. A start-up check (also a unit test) fails if any OpenAPI operation has no entry or an entry has no permission.'],
['code', `{Op: "updateChannel", Method: "PATCH", Path: "/api/v1/channels/{id}",
 Perm: authz.ConfigWrite, StepUp: false, Audit: "channel.update", Resource: "channel",
 Upstream: upstream.Core, Timeout: upstream.Write, Before: "getChannel"}`],

['h1', '3. Components'],
['table', ['Package', 'Responsibility', 'Key types / functions'], [
  ['`server`', 'builds the middleware chain (order in 05 §5.4), mounts generated handlers, serves `/health`, `/ready`, `/metrics` on the same listener', '`New(deps) http.Handler`, `Route`'],
  ['`auth`', 'hash and verify passwords, policy checks, account lockout arithmetic, dummy hash for unknown e-mails, semaphore for concurrent hashes', '`Hasher.Hash`, `Hasher.Verify(pw, phc) (ok, needsRehash)`, `Policy.Check`'],
  ['`totp`', 'generate secret, URI, verify code with skew and last-step, recovery code generation and HMAC', '`Verify(secret, code, now, lastStep) (step, ok)`'],
  ['`session`', 'create, rotate, load, touch (at most once per 60 s), end; CSRF token = HMAC(csrf key, session token); step-up timestamp', '`Store.Load(ctx, token)`, `Manager.Rotate`'],
  ['`authz`', 'role → permission set; middleware returns `403 forbidden` / `reauth_required` / `totp_required`', '`Allowed(role, perm)`'],
  ['`audit`', 'mask, write intent, complete, reconcile pending rows, retention; query for `/audit`', '`Begin(ctx, entry) (id, err)`, `Complete(ctx, id, outcome)`'],
  ['`upstream`', 'typed core calls with standard headers, per-class timeouts, one retry for idempotent reads, problem mapping; core proxy calls to module admin endpoints with `X-Admin-Actor`, capability check, field-name translation (04 §6.1) and active-module cache (30 s)', '`Core`, `Relay.Do(ctx, stage, path, ...)`'],
  ['`settings`', 'fetch, validate, cache, publish schema; typed `Snapshot` passed by value to handlers', '`Current() Snapshot`'],
  ['`ratelimit`', 'IP buckets (login, unauthenticated) and user buckets (read, write); limits from settings', '`Allow(key, class)`'],
], [1, 3.5, 2.2]],

['h1', '4. Data model (database admin)'],
['p', 'All ids are UUID v7 generated in Go. All timestamps `timestamptz` in UTC. Extension `citext` for e-mails. No table stores a secret in plaintext.'],
['h3', 'users'],
['table', ['Column', 'Type', 'Notes'], [
  ['`id`', 'uuid PK', ''],
  ['`email`', 'citext NOT NULL UNIQUE', 'login name, lower-case compare'],
  ['`name`', 'text NOT NULL', '1–100 chars'],
  ['`role`', 'text NOT NULL CHECK in (`admin`,`reviewer`,`observer`)', ''],
  ['`status`', 'text NOT NULL CHECK in (`invited`,`active`,`disabled`)', ''],
  ['`password_hash`', 'text NULL', 'PHC string; NULL while invited or after delete'],
  ['`password_changed_at`', 'timestamptz NULL', ''],
  ['`totp_secret_enc`', 'bytea NULL', 'nonce ‖ ciphertext ‖ tag, AES-256-GCM, AAD = user id'],
  ['`totp_key_version`', 'smallint NULL', 'master key version used'],
  ['`totp_enabled_at`', 'timestamptz NULL', 'NULL = 2FA not set up'],
  ['`totp_last_step`', 'bigint NOT NULL DEFAULT 0', 'replay protection'],
  ['`failed_logins`, `lock_count`', 'int NOT NULL DEFAULT 0', 'lockout state'],
  ['`locked_until`', 'timestamptz NULL', ''],
  ['`last_login_at`, `last_login_ip`', 'timestamptz, inet', ''],
  ['`created_by`', 'uuid NULL FK users', 'NULL for the first admin'],
  ['`created_at`, `updated_at`', 'timestamptz NOT NULL', ''],
], [1.6, 2.4, 2.8]],
['p', 'Indexes: unique `email`; partial `users(role) WHERE status = \'active\'` for the last-admin check.'],
['h3', 'sessions'],
['table', ['Column', 'Type', 'Notes'], [
  ['`id`', 'uuid PK', 'internal id; first 8 hex chars are the `session_ref` in logs and audit'],
  ['`token_hash`', 'bytea NOT NULL UNIQUE', 'SHA-256 of the 32-byte cookie token'],
  ['`user_id`', 'uuid NOT NULL FK users', ''],
  ['`state`', 'text CHECK in (`pending_totp`,`pending_totp_setup`,`active`)', ''],
  ['`pending_totp_secret_enc`', 'bytea NULL', 'secret during setup, moved to `users` on confirm'],
  ['`created_at`, `authenticated_at`, `last_seen_at`', 'timestamptz', '`authenticated_at` set after TOTP'],
  ['`idle_expires_at`, `absolute_expires_at`', 'timestamptz NOT NULL', 'computed from settings at creation and on touch'],
  ['`reauth_at`', 'timestamptz NULL', 'last successful step-up'],
  ['`ip`, `user_agent`', 'inet, text (≤ 256)', ''],
  ['`ended_at`, `end_reason`', 'timestamptz NULL, text NULL', '`logout`, `idle`, `absolute`, `revoked`, `password_change`, `role_change`, `disabled`, `totp_reset`, `rotated`'],
], [1.9, 2.1, 2.8]],
['p', 'Indexes: unique `token_hash`; `sessions(user_id) WHERE ended_at IS NULL`; `sessions(idle_expires_at) WHERE ended_at IS NULL` for the sweeper.'],
['h3', 'Other tables'],
['table', ['Table', 'Columns', 'Indexes / notes'], [
  ['`recovery_codes`', '`id` uuid PK, `user_id` FK, `code_hmac` bytea, `generation` int, `used_at` timestamptz NULL, `created_at`', 'unique `code_hmac`; `(user_id) WHERE used_at IS NULL`'],
  ['`invitations`', '`id`, `user_id` FK, `purpose` (`invite`|`password_reset`), `token_hash` bytea, `expires_at`, `used_at`, `created_by`, `created_at`', 'unique `token_hash`; a new link for the same user and purpose expires older ones'],
  ['`setup_tokens`', '`id`, `token_hash` bytea, `expires_at`, `used_at`, `created_at`', 'unique `token_hash`'],
  ['`audit_log`', '`id` uuid PK, `at`, `finished_at`, `actor_user_id` uuid NULL, `actor_email` text, `actor_role` text, `session_ref` text, `ip` inet, `user_agent` text, `action` text, `resource_type` text, `resource_id` text, `outcome` text CHECK (`pending`,`success`,`denied`,`failed`,`unknown`), `http_method`, `route` (template), `status_code` int, `problem_code` text, `request_id`, `trace_id`, `production_id` uuid NULL, `before` jsonb, `after` jsonb, `details` jsonb', '`(at DESC)`, `(actor_user_id, at DESC)`, `(resource_type, resource_id, at DESC)`, `(action text_pattern_ops, at DESC)`, `(production_id) WHERE production_id IS NOT NULL`, `(at) WHERE outcome = \'pending\'`. No FK to users (rows outlive users). Trigger `audit_log_guard` (05 §8.3).'],
  ['`settings_cache`', '`owner` text PK, `version` int, `values` jsonb, `fetched_at`', 'one row `admin-api`'],
], [1.2, 3.6, 2.2]],
['h2', '4.1 Migrations policy'],
['ul', [
  'goose SQL files in `internal/store/migrations/`, numbered `00001_init.sql`, embedded in the binary; `serve` applies pending migrations at start under `pg_advisory_lock(hashtext(\'admin-api-migrate\'))`; `migrate` does it without serving.',
  'Production migrations are forward-only and backward compatible with the previous binary (expand → deploy → contract), because rollback of the binary must not need a down migration.',
  'Down sections exist for local development only. Every migration has an integration test that applies it to the previous schema with seed data.',
  'Audit volume is small (hundreds of rows per day); no partitioning in stage 1. Revisit at 10 million rows.',
]],

['h1', '5. Configuration'],
['h2', '5.1 Bootstrap environment variables'],
['table', ['Variable', 'Example', 'Meaning'], [
  ['`ADMIN_DATABASE_URL`', '`postgres://admin:…@postgres:5432/admin?sslmode=disable`', 'own database only'],
  ['`ADMIN_LISTEN_ADDR`', '`:8080`', 'HTTP listener (API, health, metrics)'],
  ['`ADMIN_CORE_URL`', '`http://core:8080`', 'core internal API base'],
  ['`ADMIN_CORE_TOKEN`', '(secret)', 'service token for `/internal/v1`, issued by the core'],
  ['`ADMIN_MASTER_KEY`', '(base64, 32 bytes)', 'root of the key ring: TOTP encryption, recovery code HMAC, CSRF HMAC. Optional `ADMIN_MASTER_KEY_PREVIOUS` during rotation.'],
  ['`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`', '`http://otel-collector:4318`, `admin-api`', 'standard OpenTelemetry variables, read by the SDK'],
], [2, 2.6, 2.6]],
['p', 'The service refuses to start if any required variable is missing or the master key is not 32 bytes. Nothing else is read from the environment. Sub-keys: HKDF-SHA256(master, salt = none, info = `admin-api/totp/v1`, `admin-api/recovery/v1`, `admin-api/csrf/v1`).'],
['h2', '5.2 Settings (stored in the core)'],
['p', 'All other values are the settings document of owner `admin-api` in the core (schema and defaults in 04 §10): session timeouts, reauth window, password policy, argon2 parameters, lockout, rate limits, TOTP options, invitation TTL, audit retention, upstream timeouts, trusted proxy CIDRs, `public_origin`, `grafana_url`, body limit, refresh interval. They are edited in the panel under System settings and versioned by the core like module settings.'],
['note', 'Changing `public_origin` or `trusted_proxy_cidrs` incorrectly can lock users out (CSRF check fails, or all clients appear as the proxy IP). The panel shows a warning; recovery: fix the value with `admin-api settings-set` on the host, which writes `PUT /internal/v1/modules/admin-api/settings`, see 05 §13.'],

['h1', '6. API description and client generation'],
['ol', [
  '`admin-api/api/openapi.yaml` is written by hand (design first) from 04. It uses OpenAPI 3.0.3 because both generators support it completely; moving to 3.1 is a later, non-breaking change of the document only.',
  'Conventions inside the document: every operation has `operationId` (camelCase verb + noun), one tag per group, `x-permission`, `x-step-up`, `x-audit-action`; secret request fields are `writeOnly: true` and `x-secret: true`; all errors reference `#/components/responses/Problem*`; list responses use `Page<Item>` shapes.',
  '`make gen` runs oapi-codegen (server interface + models into `internal/gen/api.gen.go`) and sqlc. CI runs `make gen` and fails on `git diff --exit-code`.',
  '`make lint-api` runs `redocly lint` and a custom check that every operation has the three `x-` extensions and they match the route table.',
  'CI runs `oasdiff breaking origin/main:admin-api/api/openapi.yaml admin-api/api/openapi.yaml`; a breaking change needs a new major path (`/api/v2`).',
  'The panel generates its client with `npx openapi-typescript ../admin-api/api/openapi.yaml -o src/api/schema.d.ts` and uses `openapi-fetch` with a middleware that adds `X-CSRF-Token` from `/auth/me` and maps `application/problem+json` to a typed error. Panel CI fails if the generated file is stale.',
  'admin-api serves the document at `GET /api/v1/openapi.json` to authenticated users (helps debugging; not a secret, but not public either).',
]],

['h1', '7. Deployment'],
['h2', '7.1 Image'],
['code', `# admin-api/Dockerfile
FROM golang:1.25-alpine AS build
WORKDIR /src
COPY admin-api/go.mod admin-api/go.sum ./
RUN go mod download
COPY admin-api/ .
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=\${VERSION}" -o /out/admin-api ./cmd/admin-api

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/admin-api /admin-api
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/admin-api"]
CMD ["serve"]`],
['h2', '7.2 Compose service'],
['code', `admin-api:
  image: ghcr.io/t1menar/manufacture/admin-api:\${ADMIN_API_VERSION}
  environment:
    ADMIN_DATABASE_URL: \${ADMIN_DATABASE_URL}
    ADMIN_LISTEN_ADDR: ":8080"
    ADMIN_CORE_URL: "http://core:8080"
    ADMIN_CORE_TOKEN: \${ADMIN_CORE_TOKEN}
    ADMIN_MASTER_KEY: \${ADMIN_MASTER_KEY}
    OTEL_EXPORTER_OTLP_ENDPOINT: "http://otel-collector:4318"
    OTEL_SERVICE_NAME: "admin-api"
  networks: [internal]          # no published ports
  depends_on: { postgres: { condition: service_healthy } }
  healthcheck:
    test: ["CMD", "/admin-api", "healthcheck"]   # distroless has no curl
    interval: 10s
    timeout: 3s
    retries: 3
  deploy: { resources: { limits: { cpus: "1", memory: 512M } } }
  read_only: true
  security_opt: ["no-new-privileges:true"]
  stop_grace_period: 25s`],
['p', 'Secrets come from a `.env` file with mode 600 on the host (stage 1) or Docker secrets; never from the image. The service does not depend on the core being healthy at start (see NFR-AAPI-003).'],
['h2', '7.3 Reverse proxy and TLS'],
['p', 'Caddy is the only container with published ports (80, 443). It terminates TLS (ACME certificate for the public host, HTTP → HTTPS redirect, HSTS), serves the admin-panel static build at `/`, and forwards only `/api/*` to admin-api. `/health`, `/ready`, `/metrics` are never routed. Panel and API share one origin, so no CORS is needed or allowed.'],
['code', `admin.example.com {
  encode zstd gzip
  header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options nosniff
    Referrer-Policy no-referrer
    Permissions-Policy "camera=(), microphone=(), geolocation=()"
    Content-Security-Policy "default-src 'self'; img-src 'self' blob: data: https://minio.example.com; media-src 'self' https://minio.example.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    -Server
  }
  handle /api/* {
    reverse_proxy admin-api:8080 {
      header_up X-Forwarded-Proto https
      transport http { read_timeout 60s }
    }
  }
  handle {
    root * /srv/admin-panel
    try_files {path} /index.html
    file_server
  }
}`],
['p', 'The MinIO host in the CSP is the public endpoint used by presigned URLs (verify against the core and module-publish deployment). Setting `trusted_proxy_cidrs` must contain the Compose network of Caddy so that admin-api takes the client IP from the right-most untrusted `X-Forwarded-For` entry. If TLS is terminated by an external load balancer instead, Caddy runs with an internal certificate and the same rules apply.'],
['h2', '7.4 Health checks and resources'],
['table', ['Endpoint', 'Meaning', 'Checks'], [
  ['`GET /health`', 'liveness', 'process is serving; always 200 unless shutting down'],
  ['`GET /ready`', 'readiness', '`admin` DB ping < 1 s and migrations applied; body also reports `core: ok|down` and settings version, but the core state does not fail readiness'],
  ['`GET /metrics`', 'Prometheus', 'text format'],
], [1.2, 1, 4]],
['p', 'Sizing: idle RSS ≈ 30 MiB; each argon2 hash 64 MiB; concurrency 4 → limit 512 MiB. One instance in stage 1 (in-memory rate limits); running two needs shared limits, see 01 §7.'],

['h1', '8. Observability'],
['h2', '8.1 Metrics'],
['table', ['Metric', 'Type', 'Labels'], [
  ['`admin_http_requests_total`', 'counter', '`route`, `method`, `code`'],
  ['`admin_http_request_duration_seconds`', 'histogram', '`route`, `method`'],
  ['`admin_http_in_flight_requests`', 'gauge', '—'],
  ['`admin_logins_total`', 'counter', '`result` (`success`, `bad_password`, `unknown_user`, `locked`, `disabled`, `rate_limited`)'],
  ['`admin_second_factor_total`', 'counter', '`method` (`totp`, `recovery`), `result` (`success`, `invalid`, `replay`)'],
  ['`admin_totp_setups_total`', 'counter', '`result`'],
  ['`admin_reauth_total`', 'counter', '`result`'],
  ['`admin_sessions_active`', 'gauge', '`state`'],
  ['`admin_sessions_ended_total`', 'counter', '`reason`'],
  ['`admin_password_hash_seconds`', 'histogram', '`op` (`hash`, `verify`)'],
  ['`admin_password_hash_queue_wait_seconds`', 'histogram', '—'],
  ['`admin_permission_denied_total`', 'counter', '`permission`, `reason` (`forbidden`, `reauth_required`, `totp_required`)'],
  ['`admin_csrf_failures_total`', 'counter', '`reason` (`missing`, `mismatch`, `origin`)'],
  ['`admin_rate_limited_total`', 'counter', '`scope` (`login_ip`, `account`, `read`, `write`, `anonymous`)'],
  ['`admin_audit_events_total`', 'counter', '`action`, `outcome`'],
  ['`admin_audit_write_failures_total`', 'counter', '`phase` (`intent`, `complete`)'],
  ['`admin_audit_pending`', 'gauge', '—'],
  ['`admin_upstream_requests_total`', 'counter', '`upstream` (`core`, `relay`), `operation`, `code`'],
  ['`admin_upstream_duration_seconds`', 'histogram', '`upstream`, `operation`'],
  ['`admin_upstream_errors_total`', 'counter', '`upstream`, `kind` (`timeout`, `connect`, `auth`, `5xx`, `decode`)'],
  ['`admin_settings_version`', 'gauge', '—'],
  ['`admin_settings_refresh_failures_total`', 'counter', '`reason`'],
  ['`admin_db_pool_connections`', 'gauge', '`state`'],
  ['`admin_panel_client_errors_total`', 'counter', '`kind` (`render_crash`, `unhandled_rejection`, `chunk_load`, `api_contract`, `other`)'],
  ['`admin_build_info`', 'gauge (1)', '`version`, `commit`, `go_version`'],
], [2.6, 1, 3]],
['p', 'Labels are bounded: `route` is the template (`/api/v1/productions/{id}`), `operation` is the OpenAPI `operationId`. User ids, e-mails, IPs and `production_id` are never labels. Alerts (to the admins\' Telegram via Alertmanager): `admin_audit_write_failures_total` increase > 0; `admin_upstream_errors_total{kind="auth"}` > 0 (token mismatch with the core); login failures > 30 in 10 min; `admin_audit_pending` > 0 for 10 min.'],
['h2', '8.2 Logs'],
['p', 'One JSON line per request at `info` (access log) plus events. Fields: `ts`, `level`, `msg`, `service`=`admin-api`, `version`, `request_id`, `trace_id`, `span_id`, `production_id` (if any), `user_id`, `role`, `session_ref`, `method`, `route`, `status`, `duration_ms`, `ip`, `ua_hash`, `upstream`, `upstream_status`, `problem_code`, `bytes_out`. Never logged: request or response bodies of `/auth/*` (including setup and invitations), `/credentials*`, `/review/keys` (POST), `/modules/{id}/token`; headers `Cookie`, `Set-Cookie`, `Authorization`, `X-CSRF-Token`. The slog handler has a redaction hook for attribute keys in the secret list (including `claude_oauth_token`, `anthropic_api_key`, `api_key`) as a second line of defence.'],
['h2', '8.3 Traces'],
['p', 'otelhttp server span per request named by route template; child spans `db.*` (otelpgx), `argon2.verify`, `audit.begin`, `audit.complete`, `core.<operationId>` with `traceparent` propagated to the core. Attributes: `enduser.id`, `enduser.role`, `production_id`, `http.route`, `manufacture.problem_code`. Sampling: parent-based, 100 % in stage 1 (low volume).'],

['h1', '9. Security'],
['h2', '9.1 Passwords and login'],
['ul', [
  'argon2id parameters from settings; PHC string `$argon2id$v=19$m=65536,t=3,p=1$<salt>$<hash>`; comparison with `subtle.ConstantTimeCompare`.',
  'A dummy hash computed at start with current parameters is verified for unknown e-mails, so timing does not reveal accounts.',
  'Common-password list: 100 000 entries (SecLists, MIT licence — verify licence at import), embedded gzip, checked case-insensitively.',
  'Hash concurrency limited by a semaphore (`argon2_concurrency`); waiting longer than 2 s returns `503 busy` instead of exhausting memory.',
]],
['h2', '9.2 Second factor and keys'],
['ul', [
  'TOTP secret 20 bytes; encrypted with AES-256-GCM, random 12-byte nonce, AAD = user id (a copied ciphertext does not work for another user).',
  'Recovery codes: 10 codes of 10 base32 characters shown as `XXXXX-XXXXX` (50 bits each), stored as HMAC-SHA256(recovery key, normalised code).',
  'Key rotation: set `ADMIN_MASTER_KEY_PREVIOUS` to the old key and `ADMIN_MASTER_KEY` to the new one; `admin-api migrate --rewrap-keys` re-encrypts TOTP secrets and bumps `totp_key_version`; recovery codes and CSRF tokens are regenerated (users get new codes on next login, sessions are revoked).',
]],
['h2', '9.3 Sessions and CSRF'],
['ul', [
  'Cookie `__Host-mf_session`; `Secure; HttpOnly; SameSite=Strict; Path=/`; no `Max-Age` (session cookie); server-side expiry is authoritative.',
  'CSRF token = base64url(HMAC-SHA256(csrf key, session token)); returned in login, TOTP and `/auth/me` responses; checked with constant-time compare. Combined with an `Origin` check against `public_origin` and SameSite=Strict.',
  '`last_seen_at` and `idle_expires_at` are updated at most once per 60 s per session; requests with `X-Background: 1` never update them, `POST /auth/session/touch` always does.',
]],
['h2', '9.4 Transport, CORS and headers'],
['ul', [
  'Same-origin only: admin-api has no CORS middleware and never emits `Access-Control-*`. A cross-origin browser request therefore cannot read responses, and unsafe ones fail the CSRF and Origin checks.',
  'Response headers of NFR-AAPI-007 on every response; `Content-Type: application/json; charset=utf-8` or `application/problem+json`.',
  'Requests with `Content-Type` other than `application/json` on bodies → `415`. JSON decoder with `DisallowUnknownFields`, depth limit 32, size limit `max_body_bytes`.',
  'Client IP: right-most `X-Forwarded-For` hop not in `trusted_proxy_cidrs`; otherwise the TCP peer.',
]],
['h2', '9.5 Threats and controls'],
['table', ['Threat', 'Control'], [
  ['Credential stuffing / guessing', 'IP and account limits, lockout with back-off, TOTP for all roles'],
  ['Session theft (XSS in the panel)', 'HttpOnly cookie, strict CSP at the proxy, short idle timeout, step-up for sensitive writes'],
  ['CSRF', 'SameSite=Strict, CSRF header, Origin check'],
  ['Privilege escalation', 'route table completeness check, matrix tests, last-admin rule, session revocation on role change'],
  ['Data leak via upstream fields', 'response allowlisting by public schema (FR-AAPI-052)'],
  ['Secret leak in logs or audit', 'masking, redaction hook, marker tests'],
  ['Compromised core token', 'token only in env; alert on auth errors; rotation by issuing a new token in the core and restarting admin-api'],
  ['Tampering with audit', 'trigger guard, no UPDATE of final rows, DB role without superuser'],
], [2, 4.5]],

['h1', '10. Testing strategy'],
['table', ['Level', 'Scope', 'Tools and examples'], [
  ['Unit', 'argon2 PHC round-trip and rehash rule; password policy; TOTP RFC 6238 vectors, skew, replay; recovery HMAC; CSRF derivation; masker (property tests); permission matrix (table test of every route × role); problem mapping table; cursor encoding', '`go test ./internal/...`, ≥ 80 % in security packages'],
  ['Contract', '(a) every admin-api response in tests validated against `api/openapi.yaml` by kin-openapi; (b) every core call validated against `core/api/openapi.yaml`; (c) relay calls validated against the module admin endpoint shapes of 04 §6', 'run in CI on any change of either spec'],
  ['Integration', 'real PostgreSQL 17 (testcontainers) + fake core (`httptest`) + fake modules behind the fake relay: setup, invite, login, TOTP, lockout, session expiry with fake clock, CSRF, audit two-phase, core down, timeouts', '`go test ./test/integration -tags integration`'],
  ['End-to-end', 'Compose: Caddy + admin-api + real core + fake modules; scripted browser flow (Playwright, in admin-panel repo folder) for first admin → 2FA → create channel → register module → create idea', 'nightly and before release'],
  ['Security', 'cookie flags, headers, no CORS, enumeration timing, marker-secret grep over logs/spans/audit, `gosec`, `govulncheck`, OWASP ZAP baseline scan against the Compose stack', 'CI (fast parts) and nightly (ZAP)'],
  ['Load', 'k6: 20 rps mixed reads through the proxy, 20 parallel logins', 'NFR-AAPI-001, -002'],
], [1, 3.8, 2]],

['h1', '11. Local development'],
['ol', [
  '`make dev-deps` starts PostgreSQL, MinIO, the core and Caddy from `deploy/compose.dev.yml` (Caddy uses its internal CA for `https://admin.localhost`).',
  '`make run` starts admin-api with `go run ./cmd/admin-api serve` and env from `admin-api/.env.dev` (git-ignored; `.env.dev.example` committed with placeholders and a generated dev master key).',
  '`go run ./cmd/admin-api setup-token` prints the first-admin token; open `https://admin.localhost/setup#token=…`.',
  'The panel runs with `vite` behind the same Caddy (`/` → Vite dev server, `/api/*` → admin-api), so cookies, CSRF and same-origin behave exactly as in production.',
  '`make test`, `make test-integration`, `make lint`, `make gen` are the only commands CI runs.',
]],
  ],
};
