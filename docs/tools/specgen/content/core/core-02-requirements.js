// core — Requirements
const R = rows => ['table', ['ID', 'Requirement', 'Rationale', 'Acceptance check'], rows, [0.9, 3, 1.8, 2.4]];
const FR = [];
const NFR = [];
const f = (id, req, why, acc, ref) => { FR.push([id, req, why, acc, ref]); return [id, req, why, acc]; };
const n = (id, req, why, acc, ref) => { NFR.push([id, req, why, acc, ref]); return [id, req, why, acc]; };

const blocks = [
['h1', '1. Conventions'],
['p', 'MUST, SHOULD and MAY follow RFC 2119. Each requirement has a stable ID (`FR-CORE-NNN`, `NFR-CORE-NNN`); IDs are never reused. "Stage 1" requirements are mandatory now; requirements marked **(reserved)** describe data or behaviour that must not be blocked but need not be implemented.'],
['h1', '2. Functional requirements'],
['h2', '2.1 Configuration data'],
R([
  f('FR-CORE-001', 'Core MUST store brands, channels, platform accounts and routing rules and expose create, read, update and delete for each through the internal API.', 'channels and routing are edited in the admin panel, never in code', 'API tests per resource; seed has brand `itim`, channel `itim` (`en`), rule `en` → `itim`', '03 §3.1–3.4; 04 §2.1–2.4'),
  f('FR-CORE-002', 'Channel `settings` MUST be validated against the core setting `channel_settings_schema`.', 'modules rely on channel settings (reading speed, captions)', 'PATCH with `reading_wps: 50` → 422 `channel_settings_invalid`', '04 §2.2, §11.2'),
  f('FR-CORE-003', 'Core MUST support per-idea routing overrides that replace the routing rules for a language, including "no channel".', 'one idea may go elsewhere or nowhere', '`PUT /ideas/42/routing` then `GET /routing/resolve?idea_id=42` shows source `override`', '04 §2.5; 05 §3'),
  f('FR-CORE-004', 'Stages and pipelines MUST be data: stage scope and output schema, pipeline stage order, timeout, max attempts, revise target, max rounds, notify stage.', 'stages replaceable without core code changes', 'grep of non-seed Go code finds no literal `"video"`, `"review"`, `"publish"`; pipeline CRUD tests', '03 §3.7–3.8; 04 §2.10–2.11'),
  f('FR-CORE-005', 'Pipeline edits MUST NOT affect running productions (snapshot at creation).', 'predictable runs', 'edit `default-v1` timeout during a run; running jobs keep the old timeout', '05 §3'),
]),
['h2', '2.2 Ideas and productions'],
R([
  f('FR-CORE-010', 'Core MUST store ideas with integer id, text, optional language, priority, notes and status lifecycle `new → queued → in_production → done | failed | cancelled`.', 'owner manages a backlog', 'API tests for each transition; invalid transition → 409 `invalid_state`', '04 §2.6; 05 §14'),
  f('FR-CORE-011', 'The scheduler MUST start queued ideas by priority, then queue time, while running productions are below `scheduler.max_concurrent_productions`.', 'bounded cost and load', 'queue 5 ideas with limit 2 → exactly 2 running; finishing one starts the next highest priority', '05 §2'),
  f('FR-CORE-012', 'Each production MUST have exactly one variant in stage 1, in `idea.language` or else the core setting `default_language` (`en`).', 'stage 1 is English only', 'idea without language → variant `en`; settings `default_language: de` → next variant `de`', '05 §3'),
  f('FR-CORE-013', 'The variant MUST receive its channels from routing at creation; a variant with no channel is `skipped`, and if all are skipped no production is created and the idea fails with `no_route`.', 'no work without a destination', 'override `en → []` → idea `failed`, `failure.code = no_route`, no jobs', '05 §3'),
  f('FR-CORE-014', 'The data model and contracts MUST keep `language` and the variant concept so additional languages can be added without schema change.', 'localization returns later as its own stage', 'schema review: variants keyed by (production, language); planner fan-out test with 2 variants passes', '03 §3.12; 05 §4.2'),
  f('FR-CORE-015', 'Admins MUST be able to cancel a production, retry failed or needs-attention variants, grant extra review rounds and skip a variant.', 'human recovery', 'API tests for each action incl. module cancel call on live jobs', '04 §2.7; 05 §13'),
]),
['h2', '2.3 Pipeline execution'],
R([
  f('FR-CORE-020', 'For each stage core MUST create one job for production scope and one job per non-skipped variant for variant scope (fan-out).', 'stage scope semantics', 'unit test of planner with 1 and 2 variants', '05 §4.2'),
  f('FR-CORE-021', 'Jobs MUST be queued in PostgreSQL and claimed with `FOR UPDATE SKIP LOCKED`; no job is dispatched by two workers at once.', 'D7: no extra queue infrastructure', 'integration: 8 workers, 200 jobs → every job claimed once', '05 §5.1'),
  f('FR-CORE-022', 'Core MUST dispatch a job to the active, enabled, healthy module of the stage with the canonical job request including a settings snapshot and credential refs.', 'canonical contract', 'contract test: fake module validates every received request against `job-request.json`', '04 §7.2; 05 §5'),
  f('FR-CORE-023', 'Re-sends of the same job MUST carry the same `job_id` and identical body.', 'module idempotency on `job_id`', 'kill core between send and 202; after restart fake module sees same body twice', '05 §5.1'),
  f('FR-CORE-024', 'Core MUST accept progress, result and fail callbacks only from the owning module for a live job, and validate result output against the stage output schema and job checks.', 'integrity of results', 'wrong module token → 403; output without `decision` → 422; callback for timed-out job → 409', '04 §3, §8; 05 §6'),
  f('FR-CORE-025', 'Core MUST apply a deadline per job (`timeout_s` from the snapshot) and mark late jobs `timed_out`.', 'hung modules must not block productions', 'fake module that hangs → `timed_out` within deadline + sweeper interval', '05 §7'),
  f('FR-CORE-026', 'Transient failures and timeouts MUST be retried as new jobs with exponential backoff and jitter up to `max_attempts`; fatal failures MUST NOT be retried; blocked results MUST go to `needs_attention`.', 'recover from flakiness, stop on real errors', 'unit test of delay; e2e: transient ×1 then success → 2 jobs, 1 production done', '05 §8'),
  f('FR-CORE-027', 'A review rejection MUST send only that variant back to the revise target stage in `revise` mode with the reason and previous script, until the effective max rounds (default 3) is reached, then `needs_attention`.', 'minimal-edit loop with a bound', 'e2e: reject, reject, reject → variant `needs_attention` (`max_rounds`) and 3 `review_rounds` rows', '05 §9'),
  f('FR-CORE-028', 'After a stage with `notify_stage` ends (publish), core MUST deliver a notification to the active module of that stage at least once, with retries, without blocking production completion.', 'reviewers learn where the video went', 'e2e: fake review module down for 1 minute still receives notify once it is up', '05 §10'),
  f('FR-CORE-029', 'A production MUST be `done` when all variants are published or skipped, `failed` when all are terminal and any failed.', 'clear outcome', 'planner unit tests', '05 §4.5'),
  f('FR-CORE-030', 'Core MUST record per job the request, settings version, module version, output, artifacts, metrics, error and timestamps, and append an event for every state change.', 'provenance and timeline', 'job GET shows all fields; events of an e2e run cover every transition', '03 §3.13, §3.16; 04 §9'),
  f('FR-CORE-031', '(reserved) The schema MUST allow several active modules per stage with merge strategies without data migration.', 'D9', 'review of schema: `mode`, `merge`, `module_id` in live index', '05 §16'),
]),
['h2', '2.4 Modules and settings'],
R([
  f('FR-CORE-040', 'Core MUST register a module from `{id, name, stage, endpoint}` by reading its `/info`, checking contract and stage, storing schemas, creating settings version 1 from defaults and issuing a token shown once.', 'plug-in modules', 'register fake module → 201 with token; second GET has no token', '04 §6'),
  f('FR-CORE-041', 'Exactly one module MAY be active per stage in stage 1; activation MUST require enabled, `up`, valid settings.', 'D9', 'activate second module without `replace` → 409 `active_module_exists`', '04 §2.12; 05 §11.3'),
  f('FR-CORE-042', 'Core MUST health-check enabled modules (`/health`, `/ready`, auth probe) every `health.interval_s` and dispatch only to `up` modules.', 'avoid sending work into a dead module', 'stop fake module → `down` after 3 checks, jobs stay queued; start → dispatched', '05 §11.1'),
  f('FR-CORE-043', 'Core MUST refresh `/info` periodically and re-validate settings when the module schema changes.', 'module upgrades', 'fake module changes schema → `settings_valid=false`, health `degraded`', '05 §11.2'),
  f('FR-CORE-044', 'Settings of every module and of core MUST be versioned (append-only), validated against the schema, rollback-able, and the current version MUST be sent with each job.', 'D6, provenance', 'PUT → version+1; rollback creates a new version equal to the old values; job stores `settings_version`', '04 §2.13–2.14'),
  f('FR-CORE-045', 'Core MUST proxy module admin endpoints listed in `/info.admin_endpoints` for admin-api.', 'one token per module', 'proxy to unlisted path → 404', '04 §2.12'),
  f('FR-CORE-046', 'Module tokens MUST be rotatable with a grace period.', 'compromised token response', 'old token works for grace period, then 401', '04 §1.2'),
  f('FR-CORE-047', 'Core MUST let a module read its own current settings outside a job (`GET /internal/v1/modules/self/settings`, version ETag).', 'the review bot runs between jobs', 'GET with current version in `If-None-Match` → 304; after PUT → 200 with new version', '04 §4.4'),
]),
['h2', '2.5 Credentials'],
R([
  f('FR-CORE-054', 'Core MUST keep billed and estimated costs apart: `metrics.cost_estimated = true` jobs are excluded from the daily budget alert and shown as a separate total.', 'subscription use is not billed', 'result with `cost_estimated: true` and `cost_usd: 5` does not raise `budget_exceeded`; `/overview` shows `cost_today_estimated_usd`', '04 §2.16, §7.4; 03 §6.1'),
  f('FR-CORE-050', 'Credentials MUST be stored AES-256-GCM encrypted and their values MUST never be returned by the admin API or written to logs or events.', 'write-only secrets', 'API tests: no endpoint returns `value`; log grep of e2e run finds no seeded secret', '03 §3.17, §7'),
  f('FR-CORE-051', 'A module MUST read a credential only if listed in `allowed_modules` and (access `module`, or access `job` with a live job of that module listing the ref); every read attempt MUST be logged.', 'least privilege, audit', 'read without job → 403 and a `denied` log row', '04 §4.1'),
  f('FR-CORE-052', 'Only the `owner_module` MAY write a new value (token refresh).', 'Instagram token refresh', 'other module PUT → 403', '04 §4.1'),
  f('FR-CORE-053', 'Core MUST expose seconds to expiry per credential as a metric.', 'alert before Instagram token expires', '`core_credential_expiry_seconds{ref}` present', '03 §6.1'),
]),
['h2', '2.6 Internal API'],
R([
  f('FR-CORE-060', 'Core MUST expose every resource listed in contracts §2 to the admin-api principal only, with problem+json errors, cursor pagination, `If-Match` concurrency and `Idempotency-Key` on POST.', 'admin-api is the only admin client', 'OpenAPI conformance test passes for all routes', '04 §1–2'),
  f('FR-CORE-061', 'Core MUST serve short-lived presigned links for MinIO refs to admin-api and to modules for their productions.', 'watching videos; Instagram fetch', 'presign → URL works with `curl` until expiry', '04 §2.16, §4.3'),
]),
['h1', '3. Non-functional requirements'],
R([
  n('NFR-CORE-001', 'Performance: claim + send of a queued job MUST start within 2 s (p95) when a healthy module exists.', 'responsive pipeline', '`core_job_queue_wait_seconds` p95 < 2 s in e2e with no backoff', '05 §5'),
  n('NFR-CORE-002', 'Performance: internal API p95 latency MUST be < 100 ms for single-resource reads and < 300 ms for lists of 50 at 10 000 jobs in the database.', 'snappy admin panel', 'load test with `hey` against seeded DB', '03 §3 indexes'),
  n('NFR-CORE-003', 'Capacity: core SHOULD handle 1 000 jobs per day and 20 concurrent productions with the default 1 CPU / 256 MB limit.', 'tens of jobs a day expected, 10× headroom', 'synthetic e2e with fake modules', '03 §5'),
  n('NFR-CORE-004', 'Reliability: no job result accepted with 2xx may be lost; no job may be dispatched with two different job_ids for the same try.', 'trust in the engine', 'chaos test: kill -9 core 20 times during an e2e run → all productions finish, no duplicate publications', '05 §12, §15'),
  n('NFR-CORE-005', 'Recovery: after a restart core MUST resume all productions without manual action; `/ready` within 10 s of process start.', 'Compose restarts', 'chaos test timings', '05 §12'),
  n('NFR-CORE-006', 'Availability: a module outage MUST NOT fail productions before the job deadline; queued work waits.', 'modules restart independently', 'stop module 5 min with video timeout 90 min → production finishes', '05 §11'),
  n('NFR-CORE-007', 'Security: all `/internal/v1` calls MUST be authenticated by bearer token; tokens stored hashed; constant-time compare.', 'internal network is not trusted blindly', 'request without token → 401 on every route (generated test)', '03 §7'),
  n('NFR-CORE-008', 'Security: the master key MUST come only from `CORE_MASTER_KEY`; key rotation MUST be possible without downtime.', 'key hygiene', '`core keys rotate` integration test', '03 §4.1, §7'),
  n('NFR-CORE-009', 'Security: module endpoints MUST be restricted to private addresses unless explicitly allowed.', 'SSRF', 'register `http://8.8.8.8` → 422', '03 §7'),
  n('NFR-CORE-010', 'Observability: every metric in technical §6.1 MUST exist with the listed labels; `production_id` MUST NOT be a metric label.', 'dashboards and alerts', 'test scrapes `/metrics` and checks names and label sets', '03 §6.1'),
  n('NFR-CORE-011', 'Observability: every log line about a production MUST contain `production_id` and `trace_id`; outbound calls MUST carry `traceparent` and `X-Production-Id`.', 'path of a video in Loki and Tempo', 'fake module asserts headers; log test', '03 §6.2–6.3'),
  n('NFR-CORE-012', 'Operability: only `CORE_DATABASE_URL`, `CORE_LISTEN_ADDR`, `CORE_MASTER_KEY` (and `CORE_MASTER_KEY_PREVIOUS` during rotation) MAY be read from the environment; all else is core settings.', 'no hard-coded configuration', 'test runs with a clean env plus these; code search for `os.Getenv`', '03 §4'),
  n('NFR-CORE-013', 'Operability: settings changes MUST take effect within 10 s without restart (except `workers.count`, `telemetry.*`).', 'tuning without deploys', 'change `scheduler.max_concurrent_productions` → effect observed', '03 §4.2'),
  n('NFR-CORE-014', 'Maintainability: unit coverage ≥ 85 % for `engine`, `routing`, `settings`, `credentials`; `golangci-lint` clean.', 'core is the riskiest code', 'CI report', '03 §8'),
  n('NFR-CORE-015', 'Compatibility: core MUST accept module contract 1 and ignore unknown fields in module bodies; additive API changes MUST NOT break admin-api.', 'independent deploys', 'contract tests with extra fields', '04 §13'),
  n('NFR-CORE-016', 'Compatibility: migrations MUST be forward-only and expand/contract; a release MUST start on the previous release\'s schema data.', 'safe upgrades', 'upgrade test from previous tag with data', '03 §3.19'),
  n('NFR-CORE-017', 'Data retention: events kept `retention.events_days` (730), access log `retention.access_log_days` (365); productions, jobs, review rounds and publications kept forever.', 'history vs size', 'retention loop test with fake clock', '05 §1'),
]),
];

blocks.push(['h1', '4. Traceability']);
blocks.push(['table', ['Requirement', 'Satisfied by (document §section)'], [...FR, ...NFR].map(r => [r[0], r[4]]), [1, 4]]);
blocks.push(['h1', '5. Out of scope for stage 1']);
blocks.push(['ul', [
  'Several languages per production (a later `localize` stage); parallel modules per stage (reserved FR-CORE-031); Vault; live event streaming (admin-api polls).',
]]);

module.exports = {
  dir: 'core', file: 'core-02-requirements.docx',
  meta: { title: 'core — Requirements', subtitle: 'Functional and non-functional requirements with acceptance checks',
    doc: 'core-02-requirements', version: '0.2', status: 'Draft', date: '2026-11-08' },
  blocks,
};
