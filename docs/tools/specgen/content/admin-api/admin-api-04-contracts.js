const EP = ['Method', 'Path (prefix `/api/v1`)', 'Permission', 'Audit action', 'Upstream'];
const EW = [0.6, 2.3, 1.3, 1.4, 2.4];

module.exports = {
  dir: 'admin-api',
  file: 'admin-api-04-contracts.docx',
  meta: {
    title: 'admin-api — Contracts',
    subtitle: 'Public API /api/v1, consumed core and module endpoints, errors, settings schema',
    doc: 'admin-api-04-contracts', version: '0.2', status: 'Draft', date: '2026-11-08',
  },
  blocks: [
['h1', '1. Conventions'],
['table', ['Topic', 'Rule'], [
  ['Base', '`https://<public host>/api/v1`, same origin as the panel. JSON UTF-8. Request bodies require `Content-Type: application/json`.'],
  ['Source of truth', '`admin-api/api/openapi.yaml` (OpenAPI 3.0.3). This document defines its content; the admin-panel contracts (admin-panel-04 §13, P1–P14) are included here.'],
  ['IDs', 'UUID v7 strings; ideas are integers; brands, channels, stages, pipelines and modules have text ids (`itim`, `video`, `default-v1`, `video-claude`).'],
  ['Time', 'RFC 3339 UTC, e.g. `2026-11-08T14:03:00Z`. Durations in core resources are integer seconds with a `_s` suffix (`timeout_s`, as in core-04 §1.1); admin-api\'s own settings and review key `expires_in` use duration strings (`30m`, `24h`).'],
  ['Pagination', 'Query `limit` (1–200, default 50) and `cursor` (opaque string from the previous page). Response `{"items": [...], "next_cursor": "…" or null}`. No total counts; `/overview` gives counters.'],
  ['Sorting', 'Query `sort` with one field, `-` prefix for descending; allowed values per endpoint; default `-created_at`.'],
  ['Filtering', 'Query parameters named after fields (`status=running`); several values comma-separated (`status=running,failed`); time range `from` (inclusive) / `to` (exclusive) on the list\'s main timestamp; free text `q`.'],
  ['Partial update', '`PATCH` bodies contain only fields to change; `null` clears a nullable field. Optional `If-Match` (from `ETag`) is forwarded to the core; mismatch → `412 precondition_failed`.'],
  ['Optimistic concurrency', 'Settings saves and pipeline stage saves carry `base_version`; mismatch → `409 version_conflict` with `current_version`, `author`, `saved_at`.'],
  ['Allowed actions', 'Ideas and productions carry `allowed_actions`: the actions the core allows in the current state, intersected by admin-api with the caller\'s permissions. The panel enables buttons from this list only.'],
  ['Idempotency', '`POST` creates accept optional `Idempotency-Key` (UUID), forwarded to the core (proposal C6).'],
  ['Errors', 'RFC 9457 `application/problem+json`, see §7.'],
  ['Tracing', 'Every response has `X-Request-Id`. A valid client `traceparent` is used as the parent span (the panel sends one per request); `X-Production-Id` from the client is only a span attribute, the value sent to the core is taken from the path.'],
  ['Background requests', 'Header `X-Background: 1` marks a timer-driven poll: it is served normally but does not extend the session idle timeout.'],
], [1.2, 5.3]],

['h1', '2. Authentication and request headers'],
['table', ['Item', 'Contract'], [
  ['Session cookie', '`__Host-mf_session=<43-char base64url>; Path=/; Secure; HttpOnly; SameSite=Strict`. Set by `/auth/login`, `/auth/setup`, `/auth/invite/accept` (pending session) and replaced by `/auth/totp` and `/auth/totp/setup/confirm` (active session). Cleared with `Max-Age=0` on logout and on `401`.'],
  ['CSRF', 'Header `X-CSRF-Token` on `POST`, `PUT`, `PATCH`, `DELETE`. The token is in login, setup, TOTP and `/auth/me` responses (`csrf_token`). Not required on `/auth/login`, `/auth/setup`, `/auth/invite/*` (no session yet), which instead require `Origin` = `public_origin`.'],
  ['Origin', 'Unsafe requests must have `Origin` (or, if absent, `Referer`) equal to setting `public_origin`.'],
  ['2FA gate', 'TOTP is required for every role. A session with `state = totp_required` may call only `/auth/totp`, `/auth/logout`, `/auth/me`; other routes → `401 totp_required`. With `state = totp_setup_required` also `/auth/totp/setup` and `/auth/totp/setup/confirm`; other routes → `403 totp_setup_required`.'],
  ['Step-up', 'Operations marked ⇑ in §3 require `POST /auth/reauth` within `reauth_window` while setting `step_up_required` is true; otherwise `403 reauth_required`. `/auth/me` returns `reauth_valid_until`.'],
  ['No CORS', 'No `Access-Control-*` headers are ever returned; `OPTIONS` gets `405`.'],
], [1.1, 5.4]],

['h1', '3. Endpoint index'],
['p', 'Permissions are defined in 02 §4. ⇑ = step-up. "relay R" / "relay V" = core proxy to the active module of stage `review` / `video` (§9.2). Audit "—" means reads that are not audited; every `401`/`403` on an authenticated route is audited regardless.'],
['h2', '3.1 Local'],
['table', EP, [
  ['GET', '`/auth/setup/status`', 'public', '—', 'local'],
  ['POST', '`/auth/setup`', 'public + setup token', '`setup.complete`', 'local'],
  ['POST', '`/auth/invite/inspect`', 'public + link token', '—', 'local'],
  ['POST', '`/auth/invite/accept`', 'public + link token', '`invitation.accept`', 'local'],
  ['POST', '`/auth/login`', 'public', '`auth.login`', 'local'],
  ['POST', '`/auth/totp`', 'pending session', '`auth.second_factor`', 'local'],
  ['POST', '`/auth/totp/setup`', 'pending setup, or `self` ⇑ (re-enrol)', '`auth.totp_setup`', 'local'],
  ['POST', '`/auth/totp/setup/confirm`', 'pending setup or `self`', '`auth.totp_enable`', 'local'],
  ['POST', '`/auth/recovery-codes`', '`self` ⇑', '`auth.recovery_regenerate`', 'local'],
  ['POST', '`/auth/reauth`', '`self`', '`auth.reauth`', 'local'],
  ['POST', '`/auth/password`', '`self`', '`auth.password_change`', 'local'],
  ['POST', '`/auth/session/touch`', '`self`', '—', 'local'],
  ['POST', '`/auth/logout`', 'any session', '`auth.logout`', 'local'],
  ['GET', '`/auth/me`', 'any session', '—', 'local'],
  ['GET', '`/auth/sessions`', '`self`', '—', 'local'],
  ['DELETE', '`/auth/sessions/{id}`', '`self`', '`session.revoke`', 'local'],
  ['GET', '`/openapi.json`', '`self`', '—', 'local'],
  ['POST', '`/client-errors`', '`self`', '— (log + metric)', 'local'],
  ['GET', '`/users`, `/users/{id}`, `/users/{id}/sessions`', '`users.read`', '—', 'local'],
  ['POST', '`/users`', '`users.write`', '`user.create`', 'local'],
  ['PATCH', '`/users/{id}`', '`users.write` (⇑ if `role` changes)', '`user.update`', 'local'],
  ['DELETE', '`/users/{id}`', '`users.write`', '`user.delete`', 'local'],
  ['POST', '`/users/{id}/totp/reset`', '`users.write` ⇑', '`user.totp_reset`', 'local'],
  ['POST', '`/users/{id}/password-reset`', '`users.write`', '`user.password_reset_link`', 'local'],
  ['DELETE', '`/users/{id}/sessions`', '`users.write`', '`user.sessions_revoke`', 'local'],
  ['GET', '`/audit`, `/audit/{id}`', '`audit.read`', '`audit.query`', 'local'],
], EW],
['h2', '3.2 Core-backed'],
['table', EP, [
  ['GET', '`/overview`', '`overview.read`', '—', 'GET `/internal/v1/overview`'],
  ['GET', '`/brands`, `/brands/{id}`', '`config.read`', '—', 'GET `/internal/v1/brands[/{id}]`'],
  ['POST / PATCH', '`/brands`, `/brands/{id}`', '`config.write`', '`brand.create` / `.update`', 'same method and path'],
  ['GET', '`/channels`, `/channels/{id}`, `/channels/settings-schema`', '`config.read`', '—', 'GET same under `/internal/v1`'],
  ['POST / PATCH / DELETE', '`/channels`, `/channels/{id}`', '`config.write`', '`channel.create` / `.update` / `.delete`', 'same'],
  ['GET', '`/channels/{id}/accounts`', '`config.read`', '—', 'GET `/internal/v1/platform-accounts?channel_id={id}`'],
  ['POST', '`/channels/{id}/accounts`', '`config.write`', '`account.create`', 'POST `/internal/v1/platform-accounts` (adds `channel_id`)'],
  ['PATCH / DELETE', '`/accounts/{id}`', '`config.write`', '`account.update` / `.delete`', '`/internal/v1/platform-accounts/{id}`'],
  ['GET', '`/routing-rules`', '`config.read`', '—', 'GET `/internal/v1/routing-rules`'],
  ['POST / PATCH / DELETE', '`/routing-rules`, `/routing-rules/{id}`', '`config.write`', '`routing_rule.create` / `.update` / `.delete`', 'same'],
  ['GET', '`/ideas`, `/ideas/{id}`', '`ideas.read`', '—', 'GET `/internal/v1/ideas[/{id}]`'],
  ['POST / PATCH', '`/ideas`, `/ideas/{id}`', '`ideas.write`', '`idea.create` / `.update`', 'same'],
  ['POST', '`/ideas/{id}/queue`, `/ideas/{id}/unqueue`', '`ideas.write`', '`idea.queue` / `.unqueue`', 'POST `/internal/v1/ideas/{id}/queue` / `unqueue`'],
  ['DELETE', '`/ideas/{id}`', '`ideas.delete`', '`idea.delete`', 'DELETE `/internal/v1/ideas/{id}`'],
  ['GET', '`/productions`, `/productions/{id}`, `/productions/{id}/events`, `/productions/{id}/jobs`', '`productions.read`', '—', 'GET same under `/internal/v1`'],
  ['POST', '`/productions/{id}/retry`', '`productions.control`', '`production.retry`', 'POST `/internal/v1/productions/{id}/retry`'],
  ['POST', '`/productions/{id}/cancel`', '`productions.control`', '`production.cancel`', 'POST `/internal/v1/productions/{id}/cancel`'],
  ['GET', '`/jobs/{id}`', '`productions.read`', '—', 'GET `/internal/v1/jobs/{id}`'],
  ['GET', '`/artifacts/presign`', '`artifacts.read`', '`artifact.presign`', 'GET `/internal/v1/artifacts/presign`'],
  ['GET', '`/stages`', '`config.read`', '—', 'GET `/internal/v1/stages`'],
  ['GET', '`/pipelines`, `/pipelines/{id}`', '`config.read`', '—', 'GET `/internal/v1/pipelines[/{id}]`'],
  ['POST / PATCH', '`/pipelines`, `/pipelines/{id}`', '`config.write`', '`pipeline.create` / `.update`', 'same'],
  ['PUT', '`/pipelines/{id}/stages`', '`config.write`', '`pipeline.stages_replace`', 'PUT `/internal/v1/pipelines/{id}/stages`'],
  ['GET', '`/modules`, `/modules/{id}`, `/modules/{id}/info`, `/modules/{id}/health`', '`config.read`', '—', 'GET same under `/internal/v1` (`health?live=true` probes the module now; class `register`)'],
  ['POST', '`/modules`', '`modules.write`', '`module.register`', 'POST `/internal/v1/modules` (class `register`)'],
  ['PATCH / DELETE', '`/modules/{id}`', '`modules.write`', '`module.update` / `.delete`', 'same'],
  ['POST', '`/modules/{id}/activate`, `/modules/{id}/deactivate`, `/modules/{id}/refresh`', '`modules.write`', '`module.activate` / `.deactivate` / `.refresh`', 'POST same under `/internal/v1/modules/{id}`'],
  ['POST', '`/modules/{id}/token`', '`modules.token` ⇑', '`module.token_rotate`', 'POST `/internal/v1/modules/{id}/token`'],
  ['GET', '`/modules/{id}/settings`, `…/schema`, `…/versions`', '`config.read`', '—', 'GET `/internal/v1/modules/{id}/settings…` (`{id}` may be `core`)'],
  ['PUT', '`/modules/{id}/settings`', '`settings.write`', '`module.settings.update`', 'PUT `/internal/v1/modules/{id}/settings`'],
  ['POST', '`/modules/{id}/settings/rollback/{v}`', '`settings.write`', '`module.settings.rollback`', 'POST `/internal/v1/modules/{id}/settings/rollback` with `{version, comment}`'],
  ['GET', '`/admin-settings`, `/admin-settings/schema`, `/admin-settings/versions`', '`config.read`', '—', 'GET `/internal/v1/modules/admin-api/settings…`'],
  ['PUT / POST', '`/admin-settings`, `/admin-settings/rollback/{v}`', '`settings.write`', '`admin.settings.update` / `.rollback`', 'PUT `/internal/v1/modules/admin-api/settings`; rollback as above'],
  ['GET', '`/credentials`, `/credentials/{id}`', '`credentials.read`', '`credential.read_meta`', 'GET `/internal/v1/credentials[/{id}]`'],
  ['POST', '`/credentials`', '`credentials.write` ⇑', '`credential.create`', 'POST `/internal/v1/credentials`'],
  ['PUT', '`/credentials/{id}`', '`credentials.write` ⇑', '`credential.replace_value`', 'PUT `/internal/v1/credentials/{id}/value`'],
  ['PATCH / DELETE', '`/credentials/{id}`', '`credentials.write` ⇑', '`credential.update` / `.delete`', 'PATCH / DELETE `/internal/v1/credentials/{id}`'],
], EW],
['h2', '3.3 Module admin (through the core relay)'],
['table', EP, [
  ['GET', '`/review/keys`', '`review_access.read`', '—', 'relay R → GET `/admin/v1/keys`'],
  ['POST', '`/review/keys`', '`review_access.write`', '`review_key.create`', 'relay R → POST `/admin/v1/keys`'],
  ['DELETE', '`/review/keys/{id}`', '`review_access.write`', '`review_key.revoke`', 'relay R → DELETE `/admin/v1/keys/{id}`'],
  ['GET', '`/review/reviewers`', '`review_access.read`', '—', 'relay R → GET `/admin/v1/reviewers`'],
  ['PATCH', '`/review/reviewers/{id}`', '`review_access.write`', '`reviewer.update`', 'relay R → PATCH `/admin/v1/reviewers/{id}`'],
  ['DELETE', '`/review/reviewers/{id}`', '`review_access.write`', '`reviewer.revoke`', 'relay R → DELETE `/admin/v1/reviewers/{id}`'],
  ['GET', '`/review/summaries`, `/review/summaries/{id}`', '`review_access.read`', '—', 'relay R → GET `/admin/v1/summaries[/{id}]`'],
  ['POST', '`/review/summaries`', '`review_access.write`', '`review_summary.run`', 'relay R → POST `/admin/v1/summaries`'],
  ['GET', '`/video/runs`, `/video/runs/{id}`', '`productions.read`', '—', 'relay V → GET `/admin/v1/runs[/{run_id}]`'],
  ['GET', '`/video/prompts`', '`config.read`', '—', 'relay V → GET `/admin/v1/prompts`'],
  ['POST', '`/video/golden`', '`golden.run`', '`golden.run`', 'relay V → POST `/admin/v1/golden`'],
  ['GET', '`/video/golden/{id}`', '`config.read`', '—', 'relay V → GET `/admin/v1/golden/{id}`'],
], EW],

['h1', '4. Local endpoints'],
['h2', '4.1 First admin and invitations'],
['code', `GET /api/v1/auth/setup/status            -> 200 {"setup_required": true}

POST /api/v1/auth/setup
{"token": "kq3…(43 chars)", "email": "owner@example.com", "name": "Timur", "password": "correct horse battery staple"}
-> 201 Set-Cookie: __Host-mf_session=…   {"next": "totp_setup", "csrf_token": "…"}
   409 setup_not_available | 401 invalid_token | 410 token_used | 410 token_expired | 422 validation_failed

POST /api/v1/auth/invite/inspect   {"token": "…"}
-> 200 {"purpose": "invite" | "password_reset", "email": "ann@example.com", "name": "Ann", "expires_at": "…"}

POST /api/v1/auth/invite/accept    {"token": "…", "name": "Ann", "password": "…"}     (name ignored for password_reset)
-> 200 Set-Cookie (pending session)  {"next": "totp_setup" | "totp", "csrf_token": "…"}
   401 invalid_token | 410 token_used | 410 token_expired | 422 validation_failed`],
['p', 'Links have the form `https://<public host>/invite#token=<token>` (also used for password resets) and `…/setup#token=…`; the token is in the URL fragment so it never reaches proxy logs or `Referer`. Accepting an invitation or completing setup starts a pending session, so the user goes straight to TOTP enrolment.'],
['h2', '4.2 Authentication'],
['code', `POST /api/v1/auth/login          {"email": "owner@example.com", "password": "…"}
-> 200 Set-Cookie: __Host-mf_session=…
   {"next": "totp" | "totp_setup", "csrf_token": "…", "expires_at": "2026-11-08T14:08:00Z"}
   401 invalid_credentials | 429 login_locked (Retry-After) | 429 rate_limited | 403 account_disabled

POST /api/v1/auth/totp           {"code": "492039"}   or   {"recovery_code": "K7Q2M-XR4TD"}
-> 200 Set-Cookie (new token) {"next": "done", "csrf_token": "…",
        "remaining_recovery_codes": 9 /* only when a recovery code was used */}
   401 invalid_code | 401 session_expired | 429 rate_limited

POST /api/v1/auth/totp/setup     {}
-> 200 {"secret": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        "otpauth_uri": "otpauth://totp/Manufacture:owner%40example.com?secret=…&issuer=Manufacture&algorithm=SHA1&digits=6&period=30"}

POST /api/v1/auth/totp/setup/confirm   {"code": "492039"}
-> 200 Set-Cookie (new token) {"next": "done", "csrf_token": "…", "recovery_codes": ["K7Q2M-XR4TD", "…10 codes"]}

POST /api/v1/auth/recovery-codes {}            -> 200 {"recovery_codes": [...10]}
POST /api/v1/auth/reauth         {"password": "…", "code": "492039"}  -> 200 {"reauth_valid_until": "…"}
POST /api/v1/auth/password       {"current_password": "…", "new_password": "…"} -> 204 | 422 validation_failed
POST /api/v1/auth/session/touch  {}            -> 200 {"idle_expires_at": "…"}
POST /api/v1/auth/logout         {}            -> 204 (cookie cleared)

GET  /api/v1/auth/me
-> 200 {"user": {"id": "0193…", "email": "owner@example.com", "name": "Timur", "role": "admin", "totp_enrolled": true},
        "state": "active",                                  // "active" | "totp_required" | "totp_setup_required"
        "csrf_token": "…",
        "session": {"id": "…", "expires_at": "2026-11-09T02:00:00Z", "idle_expires_at": "2026-11-08T14:33:00Z"},
        "server": {"admin_api_version": "0.2.0", "default_language": "en", "grafana_url": null},
        "permissions": ["self", "ideas.read", …], "reauth_valid_until": null, "remaining_recovery_codes": 10}
   401 unauthenticated | session_expired | session_revoked

GET  /api/v1/auth/sessions       -> 200 {"items": [Session], "next_cursor": null}
DELETE /api/v1/auth/sessions/{id} -> 204`],
['p', '`session.expires_at` is the absolute expiry. `server.default_language` comes from the core setting `default_language` (cached with the settings snapshot). A `POST /auth/totp/setup` from an `active` session (re-enrolment) needs step-up; the new secret replaces the old one only after confirm, which also regenerates recovery codes.'],
['h3', 'User and Session objects'],
['table', ['Field', 'Type', 'Notes'], [
  ['`User.id`', 'uuid', ''],
  ['`User.email`', 'string (e-mail, ≤ 254)', 'unique, case-insensitive'],
  ['`User.name`', 'string 1–100', ''],
  ['`User.role`', 'enum `admin`|`reviewer`|`observer`', ''],
  ['`User.status`', 'enum `invited`|`active`|`disabled`', ''],
  ['`User.disabled`', 'boolean', '`status = disabled`; writable in PATCH'],
  ['`User.totp_enrolled`', 'boolean', ''],
  ['`User.locked_until`', 'timestamp|null', 'writable `null` to unlock'],
  ['`User.last_login_at`, `created_at`, `updated_at`', 'timestamp', ''],
  ['`Session.id`', 'uuid', 'never the token'],
  ['`Session.current`', 'boolean', 'true for the caller\'s session'],
  ['`Session.created_at`, `last_seen_at`, `idle_expires_at`, `expires_at`', 'timestamp', ''],
  ['`Session.ip`, `Session.user_agent`', 'string', ''],
], [2.4, 2, 2.2]],
['h2', '4.3 Users'],
['code', `GET  /api/v1/users?role=admin,reviewer&status=active&q=ann&sort=email&limit=50
-> 200 {"items": [User], "next_cursor": null}

POST /api/v1/users   {"email": "ann@example.com", "name": "Ann", "role": "reviewer"}
-> 201 {"user": {User, "status": "invited"}, "invite_url": "https://admin.example.com/invite#token=…",
        "invite_expires_at": "2026-11-11T14:00:00Z"}
   409 email_taken

PATCH /api/v1/users/{id}   {"role": "observer"} | {"name": "Ann K."} | {"disabled": true} | {"locked_until": null}
-> 200 {User}   409 last_admin | 403 reauth_required | 422 cannot_modify_self

DELETE /api/v1/users/{id}                -> 204   409 last_admin
POST   /api/v1/users/{id}/totp/reset     -> 204   (user must enrol again on next login)
POST   /api/v1/users/{id}/password-reset -> 201 {"reset_url": "…/invite#token=…", "expires_at": "…"}
GET    /api/v1/users/{id}/sessions       -> 200 {"items": [Session], "next_cursor": null}
DELETE /api/v1/users/{id}/sessions       -> 204`],
['h2', '4.4 Audit'],
['code', `GET /api/v1/audit?from=2026-11-01T00:00:00Z&to=2026-11-09T00:00:00Z&user_id=…&action=credential.
                 &outcome=denied,failed&resource=module&resource_id=video-claude&production_id=…&limit=100&cursor=…
-> 200 {"items": [AuditEntry], "next_cursor": "…"}

AuditEntry
{"id": "0193…", "at": "2026-11-08T14:03:00Z", "finished_at": "2026-11-08T14:03:00.180Z",
 "user": {"id": "0192…", "email": "owner@example.com", "role": "admin"}, "session_ref": "a1b2c3d4",
 "ip": "203.0.113.7", "user_agent": "Mozilla/5.0 …",
 "action": "module.settings.update", "resource": "module", "resource_id": "video-claude",
 "outcome": "success", "method": "PUT", "route": "/api/v1/modules/{id}/settings", "status": 200,
 "problem_code": null, "request_id": "…", "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "production_id": null,
 "before": {"version": 6, "values": {"model": "…"}}, "after": {"version": 7, "values": {"model": "…"}},
 "details": {"comment": "raise render timeout"}}`],
['p', '`action` is a prefix match (`credential.` returns all credential actions). Sort is always `-at`. Without `from` the query covers the last 30 days. Secrets appear only as `"***"`; `user` is null for anonymous attempts (e-mail of a failed login is kept in `details.email`).'],
['h2', '4.5 Client errors'],
['code', `POST /api/v1/client-errors
{"kind": "render_crash", "message": "TypeError: …", "route": "/productions/:id", "trace_id": "4bf9…", "panel_version": "0.2.0"}
-> 204   (429 rate_limited above 10 per minute per session)`],
['p', '`kind` ∈ `render_crash`, `unhandled_rejection`, `chunk_load`, `api_contract`, `other` (unknown values are counted as `other`); `message` ≤ 1 000 characters, `route` ≤ 200. admin-api logs one `warn` line (event `client_error`, with user id and session ref) and increments `admin_panel_client_errors_total{kind}`. Nothing is stored in the database.'],

['h1', '5. Core-backed endpoints'],
['p', 'Unless stated, bodies equal the core internal API bodies (core-04-contracts) filtered to the fields below; admin-api removes undeclared fields and intersects `allowed_actions` with the caller\'s permissions. Every call made for a user sends the acting user to the core in `X-Admin-Actor: <user id>` and `X-Admin-Actor-Email`.'],
['h2', '5.1 Brands, channels, accounts, routing'],
['table', ['Object', 'Fields (writable in bold)'], [
  ['Brand', '`id` (text, **on create**, `^[a-z0-9-]{2,32}$`), **`name`**, `created_at`, `updated_at`. Example `{"id": "itim", "name": "iTim"}`'],
  ['Channel', '`id` (text, **on create**), **`brand_id`** (create only), **`name`**, **`language`** (ISO 639-1, create only), **`enabled`**, **`settings`** (validated by the core against `GET /channels/settings-schema`), `accounts_count`, `created_at`, `updated_at`'],
  ['PlatformAccount', '`id`, `channel_id`, **`platform`** (`instagram`; `youtube`, `tiktok` later), **`handle`**, **`external_id`**, **`credential_id`**, **`enabled`**, `created_at`, `updated_at`'],
  ['RoutingRule', '`id`, **`language`**, **`channel_id`**, **`priority`** (int), **`enabled`**, `created_at`, `updated_at`; unique (`language`, `channel_id`) → `409 conflict`'],
], [1.2, 5.3]],
['code', `POST /api/v1/channels
{"id": "itim", "brand_id": "itim", "name": "iTim", "language": "en", "enabled": true,
 "settings": {"reading_wps": 3.5, "caption_template": "{title}\\n\\n{body}", "hashtags": ["#postgres", "#internals"]}}
-> 201 {Channel, "accounts_count": 0}          409 conflict | 422 validation_failed
GET    /api/v1/channels/settings-schema        -> 200 {JSON Schema 2020-12 of channels.settings}
DELETE /api/v1/channels/{id}                   -> 204 | 409 conflict (used by routing rules or productions)
POST   /api/v1/routing-rules  {"language": "en", "channel_id": "itim", "priority": 100, "enabled": true} -> 201 {RoutingRule}`],
['h2', '5.2 Ideas'],
['table', ['Field', 'Type', 'Notes'], [
  ['`id`', 'integer', 'assigned by the core'],
  ['**`text`**', 'string 10–500, no line breaks', 'the one-line idea'],
  ['**`priority`**', 'integer 0–100, default 50', 'higher first'],
  ['**`notes`**', 'string ≤ 2000 or null', 'free text for the video module'],
  ['`language`', 'string, read-only', 'core value, or core setting `default_language` (`en`) when the core stores null; never accepted in requests'],
  ['`status`', 'enum `new`|`queued`|`in_production`|`done`|`failed`|`cancelled`', 'read-only'],
  ['`latest_production_id`', 'uuid|null', 'read-only'],
  ['`failure`', '`{code, message}`|null', 'read-only'],
  ['`allowed_actions`', 'array of `edit`, `queue`, `unqueue`, `delete`', 'core state rules ∩ caller permissions; core action `routing` is removed (not exposed)'],
  ['`productions`', 'array `{id, status, started_at, finished_at}`', 'only in `GET /ideas/{id}`'],
  ['`created_by`, `created_at`, `updated_at`', '', 'read-only'],
], [1.6, 2.6, 2.3]],
['p', 'Filters: `status`, `q` (text, notes), `from`, `to` (created_at); sort `created_at`, `priority`. `PATCH` text only in status `new` or `queued`, priority and notes always (core `409 invalid_state` otherwise). `DELETE` needs `ideas.delete` (admin only) and is allowed only in `new`, `queued` or `cancelled` without productions (core `409 in_use` / `invalid_state`). `POST /ideas/{id}/queue` moves `new`/`failed`/`cancelled` → `queued`; `unqueue` moves `queued` → `new`. The public limits (text 10–500, priority 0–100 default 50, notes ≤ 2000) are a stricter subset of the core\'s; admin-api sends `priority: 50` when the client omits it.'],
['note', 'The core keeps an optional idea `language`, `pipeline_id` and per-idea routing overrides (core-04 §2.5–2.6) for later localization. admin-api deliberately does not expose them in stage 1: no request field, no endpoint, and the `routing` allowed action is filtered out. Exposing them later is an additive change.'],
['code', `POST /api/v1/ideas  {"text": "How CREATE DATABASE copies the template in PostgreSQL", "priority": 70, "notes": null}
-> 201 {"id": 42, "text": "…", "language": "en", "priority": 70, "notes": null, "status": "new",
        "latest_production_id": null, "failure": null, "allowed_actions": ["edit", "queue", "delete"], "created_by": "owner@example.com", …}`],
['h2', '5.3 Productions and jobs'],
['code', `GET /api/v1/productions?status=running&variant_status=needs_attention&idea_id=42&channel_id=itim&from=…&to=…
-> {"items": [ProductionSummary], "next_cursor": …}
ProductionSummary = {"id", "idea": {"id", "text"}, "status", "stage", "channel_ids": ["itim"], "started_at", "finished_at", "cost_usd"}

GET /api/v1/productions/{id}  -> ProductionDetail = ProductionSummary + {
  "pipeline_id": "default-v1", "current_position": 2, "trace_id": "0193…",
  "allowed_actions": ["retry:video", "cancel"], "language": "en",
  "totals": {"cost_usd": 1.84, "cost_estimated_usd": 0.0, "tokens_in": 120000, "tokens_out": 8000},   // cost_usd billed only; cost_estimated_usd = estimates (e.g. subscription use) "live_jobs": [JobSummary], "failure": null,
  "provenance": {"commit": "…", "settings_versions": {"video-claude": 7}, "prompt_versions": {…}},
  "variants": [{                                   // exactly one in stage 1
    "id": "0193…", "language": "en", "status": "in_review", "stage_id": "review", "position": 2,
    "review_round": 2, "max_rounds": 3, "channels": ["itim"],
    "attention": null,   // {reason: max_rounds|blocked|timeout|publish_partial|retries_exhausted, job_id, code?, message, retry_after?}  code e.g. agent_auth_failed
    "video": {"ref": "s3://manufacture/<pid>/video/2/final.mp4", "sha256": "…", "duration_s": 58.4,
              "size": 18234112, "width": 1080, "height": 1920, "fps": 30},
    "cover": {"ref": "s3://…"}, "contact_sheet": {"ref": "s3://…"},
    "post": {"caption": "…", "hashtags": ["postgres", "internals"]},
    "checks": {"loudness": {"status": "pass", "value": "-14.1 LUFS"}},
    "changes": "Shortened the intro as requested",
    "review_rounds": [{"round": 1, "decision": "rejected", "reason": "…",
                       "reviewer": {"telegram_user_id": 123, "username": "tim"}, "decided_at": "…"}],
    "publications": [{"platform": "instagram", "platform_account_id": "…", "account_handle": "itim",
                      "external_post_id": "…", "url": "https://…", "published_at": "…", "status": "published", "error": null,
                      "error_detail": null, "dry_run": false}]}]}

GET /api/v1/productions/{id}/events?after=1234&limit=200   -> {"items": [{"id": 1235, "type": "job.succeeded", "at": "…", "payload": {…}}], "next_cursor": …}  (ascending)
GET /api/v1/productions/{id}/jobs                           -> {"items": [Job], …}
GET /api/v1/jobs/{id}  -> Job = {"id", "production_id", "variant_id", "stage_id", "module_id", "position", "attempt", "try",
     "max_attempts", "mode", "round", "status", "progress": {"percent", "step", "message", "at"}, "settings_version",
     "module_version", "run_after", "deadline", "dispatched_at", "started_at", "finished_at",
     "metrics": {"cost_usd", "cost_estimated", "tokens_in", "tokens_out"}, "error": {"class", "message"} | null,
     "request": {…}, "output": {…}, "artifacts": [{"ref", "sha256", "size", "kind"}]}     // request, output, artifacts: detail only
POST /api/v1/productions/{id}/retry   {"stage": "video", "variant_id": null}  -> 202 {"job_id": "…"}
POST /api/v1/productions/{id}/cancel  {"reason": "duplicate idea"}           -> 200 {ProductionDetail}`],
['p', 'The variant fields come from the canonical `video`, `review` and `publish` stage outputs as stored by the core; `account_handle` is joined by the core. Job `request` and `output` contain credential references (`cred:…`), never values. `allowed_actions` entries `retry:<stage>` and `cancel` are removed for callers without `productions.control`; the core actions `skip:<variant_id>` and `extra_rounds:<variant_id>` are removed for everyone, because admin-api does not expose them in stage 1 (later). Status values (core-04 §2.7, §2.9): production `running`, `done`, `failed`, `cancelled` (a production stays `running` while a variant needs attention); variant `pending`, `producing`, `in_review`, `revising`, `approved`, `publishing`, `published`, `skipped`, `failed`, `needs_attention`, `cancelled`; job `queued`, `dispatching`, `dispatched`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`. Unknown values are passed through as strings. Cost: `totals.cost_usd` is billed cost only; `totals.cost_estimated_usd` sums jobs whose `metrics.cost_estimated` is true (for example use of the Claude subscription, which is not billed). The panel must label estimated cost as an estimate and never add it to billed cost. `ProductionSummary.cost_usd` is billed cost. `attention.code` is a machine code from the module or core (for example `agent_auth_failed`), shown next to `message`.'],
['h2', '5.4 Artifacts'],
['code', `GET /api/v1/artifacts/presign?ref=s3://manufacture/0193…/video/2/final.mp4&disposition=inline|attachment
-> 200 {"url": "https://minio.example.com/manufacture/…?X-Amz-…", "expires_at": "2026-11-08T14:18:00Z"}
   400 invalid_ref (not under s3://manufacture/) | 404 not_found`],
['p', 'admin-api checks the `ref` prefix before forwarding; `attachment` makes the URL download with the object\'s file name. URL lifetime is the core setting (default 15 min). The audit row stores the `ref`, not the URL.'],
['h2', '5.5 Stages and pipelines'],
['code', `GET /api/v1/stages -> {"items": [{"id": "video", "name": "Video", "scope": "production", "active_module_id": "video-claude"}, …]}
GET /api/v1/pipelines/default-v1
-> {"id": "default-v1", "name": "Default v1", "is_default": true, "version": 3,
    "enabled": true,
    "stages": [{"position": 1, "stage_id": "video", "timeout_s": 5400, "max_attempts": 2, "mode": "single", "merge": "first_success",
                "revise_target": null, "max_rounds": null, "notify_stage": null}, …]}
PATCH /api/v1/pipelines/default-v1   {"name"?, "is_default"?, "enabled"?}  -> 200 {Pipeline}
PUT /api/v1/pipelines/default-v1/stages
{"base_version": 3,
 "stages": [{"position": 1, "stage_id": "video",   "timeout_s": 5400,   "max_attempts": 2, "mode": "single", "merge": "first_success"},
            {"position": 2, "stage_id": "review",  "timeout_s": 604800, "max_attempts": 1, "mode": "single", "merge": "first_success",
             "revise_target": "video", "max_rounds": null},
            {"position": 3, "stage_id": "publish", "timeout_s": 1800,   "max_attempts": 3, "mode": "single", "merge": "first_success",
             "notify_stage": "review"}]}
-> 200 {Pipeline, "version": 4}    409 version_conflict | 422 validation_failed (invalid order)`],
['p', '`timeout_s` is an integer (10–2 592 000). `mode` accepts only `single` in stage 1 (`parallel` → `422 not_supported`). `merge` is never null: `first_success` (default, sent by admin-api when omitted), `all`, `vote` or `module:<id>`, reserved for parallel mode. `revise_target`, `max_rounds`, `notify_stage` as core-04 §2.11.'],
['h2', '5.6 Modules'],
['code', `POST /api/v1/modules
{"id": "publish-social", "name": "Publish (social)", "stage": "publish", "endpoint": "http://module-publish:8080", "enabled": true}
-> 201 {Module, "token": "mft_…"}          // token shown once; set as MODULE_CORE_TOKEN of the module
   409 conflict | 422 module_contract_unsupported | 422 module_stage_mismatch | 502 module_unreachable

Module = {"id", "name", "stage_id", "endpoint", "version", "contract", "enabled", "active",
          "health": "unknown|up|degraded|down|unauthorized",
          "health_detail": {"reason", "health_status", "ready_status", "auth_probe", "latency_ms", "checked_at"},
          "settings_version", "settings_valid", "token_prefix", "last_seen_at", "info_refreshed_at",
          "admin_endpoints": ["/admin/v1/keys"], "stats_24h": {"succeeded": 3, "failed": 0, "timed_out": 0}, "created_at", "updated_at"}

POST /api/v1/modules/{id}/activate  {"replace": false}  -> 200 {"module": {Module}, "deactivated": "review-old" | null}
   409 active_module_exists (send replace: true) | 409 module_not_ready | 422 validation_failed (settings invalid)
POST /api/v1/modules/{id}/deactivate  -> 200 {Module}       POST /api/v1/modules/{id}/refresh  -> 200 {Module}  (re-read /info)
PATCH /api/v1/modules/{id}  {"name"?, "endpoint"?, "enabled"?}  -> 200 {Module}
DELETE /api/v1/modules/{id}  -> 204   409 module_active (core in_use: active or used by a job; disable instead)
POST /api/v1/modules/{id}/token  {}   -> 200 {"token": "mft_…", "token_prefix": "mft_ab12", "prev_token_expires_at": "…"}   (old token valid for the core grace period)
GET  /api/v1/modules/{id}/health?live=true -> 200 {"health": "up|degraded|down|unauthorized|unknown", "reason": null, "latency_ms": 12, "checked_at": "…"}
GET  /api/v1/modules/{id}/info       -> 200 {stored canonical /info body}`],
['p', 'Token fields are never stored or logged by admin-api and are masked in audit rows.'],
['h2', '5.7 Module, core and admin-api settings'],
['code', `GET /api/v1/modules/video-claude/settings
-> 200 SettingsVersion = {"module_id": "video-claude", "version": 7, "values": {…}, "valid": true, "author": "user:0192…",
        "author_email": "owner@example.com", "comment": "…", "rolled_back_from": null, "created_at": "…", "is_current": true,
        "validation_errors": [{"pointer": "/render/timeout", "message": "…"}]}   // non-empty after a schema change
GET /api/v1/modules/video-claude/settings/schema   -> 200 {JSON Schema 2020-12}
PUT /api/v1/modules/video-claude/settings  {"base_version": 7, "values": {…}, "comment": "longer render timeout"}
-> 201 {SettingsVersion, "version": 8}
   409 version_conflict {"current_version": 8, "author": "…", "saved_at": "…"} | 422 validation_failed (errors[] with pointers)
GET /api/v1/modules/video-claude/settings/versions?limit=20  -> {"items": [SettingsVersion], …}   (values included)
POST /api/v1/modules/video-claude/settings/rollback/5  {"comment": "back to 5"}  -> 201 {SettingsVersion, "version": 9}`],
['p', 'Public `POST …/rollback/{v}` is sent to the core as `POST /internal/v1/modules/{id}/settings/rollback {version: v, comment}`; core `settings_version_conflict` is published as `version_conflict`, `settings_invalid` as `validation_failed`. The core\'s own settings use module id `core` on the same endpoints. admin-api\'s own settings use `/admin-settings`, `/admin-settings/schema`, `/admin-settings/versions`, `/admin-settings/rollback/{v}` with the same shapes (`module_id` = `admin-api`); after a successful save admin-api refreshes its snapshot at once.'],
['h2', '5.8 Credentials'],
['code', `GET /api/v1/credentials?kind=oauth_token&q=insta
-> {"items": [CredentialMeta], "next_cursor": null}
CredentialMeta = {"id": "0192…", "name": "instagram-itim", "ref": "cred:instagram-itim", "kind": "oauth_token",
                  "last4": "x9Qa", "expires_at": "2027-01-05T00:00:00Z", "allowed_modules": ["publish-social"],
                  "access": "job", "owner_module": "publish-social", "rotated_at": "…", "created_at": "…", "updated_at": "…", "last_used_at": "…"}
POST  /api/v1/credentials  {"name": "anthropic-main", "kind": "claude_oauth_token", "value": "<secret from claude setup-token>", "expires_at": null, "allowed_modules": ["video-claude"]}
-> 201 {CredentialMeta}
PUT   /api/v1/credentials/{id}  {"value": "<secret>", "expires_at": "2027-01-05T00:00:00Z"}  -> 200 {CredentialMeta}
PATCH /api/v1/credentials/{id}  {"name"?, "access"?, "allowed_modules"?, "owner_module"?, "expires_at"?}  -> 200 {CredentialMeta}
DELETE /api/v1/credentials/{id} -> 204
   409 credential_in_use {"references": [{"kind": "platform_account", "id": "…", "name": "itim"}, {"kind": "settings", "id": "video-claude", "name": "…"}]}`],
['p', '`name` is a slug of 2–64 characters. `kind` ∈ `api_key`, `anthropic_api_key` (Anthropic API key), `claude_oauth_token` (token from `claude setup-token`, used by module-video in its default subscription mode), `oauth_token`, `bot_token`, `password`, `s3_keys`, `generic`; `access` ∈ `job`, `module` (core-04 §4.1). Access log items are `{principal, job_id, action, outcome, at}`. `value` is `writeOnly` and `x-secret`, 1–16 384 bytes; no response contains it, and admin-api does not decode a field named `value` from any credential response.'],
['h2', '5.9 Overview'],
['code', `GET /api/v1/overview
-> 200 {"counts": {"ideas_queued": 3, "productions_running": 1, "waiting_review": 1, "published_today": 2, "failed_24h": 0,
                   "needs_attention": 0, "jobs_queued": 0,
                   "cost_today_usd": 1.2, "cost_today_estimated_usd": 3.4},
        "active": [{"production_id": "…", "idea": {"id": 42, "text": "…"}, "status": "running", "stage": "video",
                    "progress": {"percent": 40, "step": "render"}, "started_at": "…"}],
        "waiting_review": [{"production_id": "…", "variant_id": "…", "idea_text": "…", "round": 2, "since": "…"}],
        "modules": [{"stage": "video", "module_id": "video-claude", "health": "up", "version": "0.1.0", "last_seen_at": "…"}],
        "alerts": [{"kind": "credential_expiring", "severity": "warning", "message": "…",
                    "resource": "credential", "resource_id": "…", "at": "…"}],
        "publications_today": [{"production_id": "…", "platform": "instagram", "account_handle": "itim",
                                "url": "https://www.instagram.com/reel/…", "published_at": "…"}]}`],
['p', 'Alert messages read `<code>: <message>`. Alert `kind`: `production_failed`, `needs_attention`, `review_waiting`, `module_unhealthy`, `credential_expiring`, `credential_expired`, `publish_failed`, `budget_exceeded` (counts billed cost only; estimates never trigger it). `counts.cost_today_usd` is billed cost for the UTC day and `counts.cost_today_estimated_usd` the estimate. The whole object is computed by the core; if the core is down admin-api returns `503 upstream_unavailable`.'],

['h1', '6. Module admin endpoints'],
['h2', '6.1 Review access (module-review, stage review)'],
['code', `GET  /api/v1/review/keys?status=unused,used,expired,revoked
-> {"items": [AccessKey], "next_cursor": null}
AccessKey = {"id": "…", "hint": "…x7Qa", "role": "reviewer", "note": "Ann phone", "created_by": "<user id or e-mail>",
             "created_via": "admin_api|bot", "created_at": "…", "expires_at": "…", "status": "unused|used|expired|revoked",
             "used_at": null, "used_by": {"reviewer_id": "…", "telegram_user_id": 123, "username": "ann"} | null, "revoked_at": null}
POST /api/v1/review/keys   {"role": "reviewer", "expires_in": "24h", "note": "Ann phone"}
-> 201 {AccessKey, "key": "rvk_…", "start_link": "https://t.me/<bot_username>?start=rvk_…"}   (key and link shown once)
DELETE /api/v1/review/keys/{id}       -> 204   409 conflict (key already used: revoke the reviewer instead)

GET  /api/v1/review/reviewers?status=active,revoked
-> {"items": [{"id": "…", "telegram_user_id": 123456789, "username": "ann", "display_name": "Ann", "role": "reviewer",
               "language": null, "status": "active", "bound_at": "…", "revoked_at": null, "last_seen_at": "…",
               "decisions": {"approved": 12, "rejected": 3}}], "next_cursor": null}
PATCH  /api/v1/review/reviewers/{id}  {"role": "admin"}  -> 200 {Reviewer}
DELETE /api/v1/review/reviewers/{id}  -> 204

GET  /api/v1/review/summaries        -> {"items": [{"id", "period_start", "period_end", "trigger", "status", "input_count",
                                                     "model", "prompt_version", "cost_usd", "created_at"}], "next_cursor": null}
GET  /api/v1/review/summaries/{id}   -> {Summary, "output": {…}}     (output schema: module-review-06 §2.4)
POST /api/v1/review/summaries {"window": "7d", "send": false}  -> 202 {"id": "…", "status": "running"}`],
['p', 'Telegram roles (`admin`, `reviewer`, `observer`) are module-review roles, independent of panel roles; `expires_in` 1h–720h. admin-api translates between the public names (from the panel contract) and module-review\'s names: `expires_in` ↔ `ttl`, `start_link` ↔ `deep_link`, key status `unused` ↔ `active`; other fields pass through. Module codes map to public ones: `key_already_used` → `409 conflict`, `ttl_too_long` and `invalid_request` → `422 validation_failed`, `not_found` → `404`; `actor_required` and `unauthorized` mean a relay misconfiguration → `502 upstream_error`. `key` and `start_link` are masked in audit and never logged. Summaries are produced by module-review with Claude; admin-api only shows them.'],
['h2', '6.2 Video runs, prompts and golden runs (module-video, stage video)'],
['code', `GET  /api/v1/video/runs?production_id=…&status=running&limit=50&cursor=…
-> {"items": [VideoRun], "next_cursor": null}
VideoRun = {"id": "…", "job_id": "…", "production_id": "…", "mode": "create|revise", "status": "…", "current_step": "render",
            "cost_usd": 1.2, "started_at": "…", "finished_at": null}
GET  /api/v1/video/runs/{id}  -> {VideoRun, "steps": [{"name", "status", "started_at", "finished_at", "cost_usd"}],
                                  "checks": {…}, "agent_runs": [{"step", "turns", "cost_usd", "stop_reason"}],
                                  "artifacts": [{"ref", "kind"}], "transcript_refs": ["s3://…"]}
GET  /api/v1/video/prompts    -> {"items": [{"step": "script", "versions": ["1.0.0", "1.1.0"], "default": "1.0.0", "sha256": {"1.0.0": "…"}}]}
POST /api/v1/video/golden     {"settings": {…}, "overrides": {"prompt_versions": {"script": "1.1.0"}}, "ideas": ["create-database"]}
-> 202 {"golden_run_id": "…"}
GET  /api/v1/video/golden/{id} -> {"id", "status", "results": [{"idea", "status", "failed_checks": [...], "duration_s", "cost_usd",
                                   "contact_sheet_ref", "diff": {…}}], "created_at", "finished_at"}`],
['p', 'Shapes follow module-video-04 (admin endpoints); nested `checks`, `diff` and `settings` are typed as free-form objects because module-video owns their schema. Transcript and artifact refs open through `/artifacts/presign`. A golden run spends model budget, so it needs `golden.run` (admin) and is audited with the body masked as usual. The stage 1 panel has no screens for these endpoints.'],
['h1', '7. Errors'],
['p', 'Body: `{"type": "urn:manufacture:problem:<code>", "title": "<fixed per code>", "status": <int>, "detail": "<human text>", "code": "<code>", "request_id": "…", "errors": [{"pointer": "/text", "code": "too_short", "message": "…"}]}`. Some codes add members: `version_conflict` → `current_version`, `author`, `saved_at`; `credential_in_use` → `references`. `detail` never contains secrets or upstream internals.'],
['table', ['Status', 'code', 'When'], [
  ['400', '`bad_request`, `invalid_cursor`, `invalid_ref`', 'malformed JSON or query; bad cursor; artifact ref outside the bucket'],
  ['401', '`unauthenticated`, `session_expired`, `session_revoked`, `totp_required`, `invalid_credentials`, `invalid_code`, `invalid_token`', 'no or bad session; second factor pending; wrong password / code; bad setup or link token'],
  ['403', '`forbidden`, `csrf_invalid`, `totp_setup_required`, `reauth_required`, `account_disabled`', 'permission, CSRF / Origin, enrolment pending, step-up'],
  ['404', '`not_found`', 'resource does not exist (local or upstream)'],
  ['405 / 415', '`method_not_allowed`, `unsupported_media_type`', ''],
  ['409', '`conflict`, `invalid_state`, `email_taken`, `last_admin`, `setup_not_available`, `version_conflict`, `module_active`, `active_module_exists`, `module_not_ready`, `credential_in_use`, `module_not_available`, `module_capability_missing`', 'state conflicts; no active module for the stage; module lacks the admin endpoint'],
  ['410', '`token_used`, `token_expired`', 'setup or invitation link'],
  ['412', '`precondition_failed`', '`If-Match` mismatch'],
  ['413', '`payload_too_large`', 'body over `max_body_bytes`'],
  ['422', '`validation_failed`, `cannot_modify_self`, `not_supported`, `module_contract_unsupported`, `module_stage_mismatch`, `idempotency_key_reused`', 'schema or business validation with `errors[]`; password codes in `errors[].code`: `password_too_short`, `password_too_common`, `password_matches_identity`'],
  ['429', '`rate_limited`, `login_locked`', 'with `Retry-After`'],
  ['500', '`internal`', 'bug; details only in logs'],
  ['502', '`upstream_error`, `module_unreachable`', 'core answered 5xx, 401/403 to admin-api, or an undecodable body; module unreachable from the core relay'],
  ['503', '`upstream_unavailable`, `audit_unavailable`, `busy`', 'core not reachable; audit store down; password hashing queue full; with `Retry-After`'],
  ['504', '`upstream_timeout`', 'upstream exceeded its timeout class'],
], [0.8, 3, 2.8]],

['h2', '7.1 Core codes published under another name'],
['table', ['Core code (core-04 §10)', 'Public code'], [
  ['`already_exists`, `in_use` (except module delete)', '`409 conflict`'],
  ['`in_use` on module delete', '`409 module_active`'],
  ['`settings_version_conflict`; `version_mismatch` on `PUT /pipelines/{id}/stages`', '`409 version_conflict`'],
  ['`version_mismatch` on `If-Match`', '`412 precondition_failed`'],
  ['`unknown_field`, `settings_invalid`, `channel_settings_invalid`, `schema_invalid`, `pipeline_invalid`', '`422 validation_failed` (core `errors[]` kept; core code in `detail`)'],
  ['`unauthorized`, `forbidden` (admin-api token problem)', '`502 upstream_error`'],
  ['`unavailable`', '`503 upstream_unavailable`'],
  ['all other client codes', 'unchanged'],
], [3.5, 3]],
['h1', '8. Internal endpoints (not routed by the proxy)'],
['table', ['Endpoint', 'Response'], [
  ['`GET /health`', '`200 {"status": "ok"}`; `503` while draining'],
  ['`GET /ready`', '`200 {"status": "ready", "db": "ok", "migrations": 5, "core": "ok|down", "settings_version": 3}`; `503` if the DB fails'],
  ['`GET /metrics`', 'Prometheus text format, metrics of 03 §8.1'],
], [1.5, 5]],

['h1', '9. Consumed interfaces'],
['h2', '9.1 Core internal API'],
['p', 'Base `ADMIN_CORE_URL` + `/internal/v1`. Headers on every call: `Authorization: Bearer <ADMIN_CORE_TOKEN>`, `traceparent`, `X-Request-Id`, `X-Admin-Actor: <user id>` and `X-Admin-Actor-Email: <e-mail>` (absent for system calls such as settings refresh), `X-Production-Id` for production, job and artifact calls, `Idempotency-Key` and `If-Match` when the client sent them. The core answers RFC 9457 problems with the same `code` vocabulary for client errors.'],
['table', ['Core endpoint (all under `/internal/v1`)', 'Used by', 'core-04'], [
  ['`GET|POST /brands`, `GET|PATCH /brands/{id}`', 'brands', '§2.1'],
  ['`GET|POST /channels`, `GET|PATCH|DELETE /channels/{id}`, `GET /channels/settings-schema`', 'channels', '§2.2'],
  ['`GET|POST /platform-accounts`, `GET|PATCH|DELETE /platform-accounts/{id}`', 'accounts', '§2.3'],
  ['`GET|POST /routing-rules`, `PATCH|DELETE /routing-rules/{id}`', 'routing', '§2.4'],
  ['`GET|POST /ideas`, `GET|PATCH|DELETE /ideas/{id}`, `POST /ideas/{id}/queue`, `POST /ideas/{id}/unqueue`', 'ideas (idea routing overrides §2.5 not used in stage 1)', '§2.6'],
  ['`GET /productions`, `GET /productions/{id}`, `…/events?after=`, `…/jobs`, `POST …/retry {stage, variant_id}` → `202 {job_id}`, `POST …/cancel`', 'productions (variant retry and skip not used in stage 1)', '§2.7, §2.8'],
  ['`GET /jobs/{id}`', 'job detail', '§2.9'],
  ['`GET /stages` (with `active_module_id`)', 'stages, module proxy resolution', '§2.10'],
  ['`GET|POST /pipelines`, `GET|PATCH /pipelines/{id}`, `PUT /pipelines/{id}/stages {stages, base_version}`', 'pipelines', '§2.11'],
  ['`GET|POST /modules`, `GET|PATCH|DELETE /modules/{id}`, `POST …/activate|deactivate|refresh|token`, `GET …/info`, `GET …/health?live=`', 'modules', '§2.12'],
  ['`ANY /modules/{id}/admin/v1/{path}`', 'module admin proxy (8 s core-side timeout)', '§2.12'],
  ['`GET|PUT /modules/{owner}/settings`, `GET …/schema`, `GET …/versions[/{v}]`, `POST …/rollback {version, comment}` for any module, `core`, `admin-api`; `PUT /modules/admin-api/settings/schema`', 'module, core and admin-api settings', '§2.13, §2.14'],
  ['`GET|POST /credentials`, `GET|PATCH|DELETE /credentials/{id}`, `PUT /credentials/{id}/value`', 'credentials', '§2.15'],
  ['`GET /artifacts/presign?ref=&disposition=`, `GET /overview`', 'artifacts, overview', '§2.16'],
  ['`GET /health`', 'readiness detail', '§5'],
], [3.6, 1.6, 0.8]],
['h2', '9.2 Core relay to module admin endpoints'],
['ol', [
  'admin-api resolves the active module of the stage from `GET /internal/v1/stages` (`active_module_id`) and `GET /internal/v1/modules/{id}` (`admin_endpoints`), cached 30 s. No active module → `409 module_not_available`; path not listed → `409 module_capability_missing`.',
  'admin-api calls `{method} /internal/v1/modules/{module_id}/admin/v1/keys…` with its core service token, the standard headers (including `X-Admin-Actor`) and the body translated to the module\'s field names.',
  'The core checks that the path is in the module\'s `admin_endpoints`, forwards to `{endpoint}/admin/v1/keys…` with `Authorization: Bearer <module token>`, `traceparent` and `X-Admin-Actor`, and returns the module response unchanged. Core-side timeout 8 s (below admin-api\'s 10 s).',
  'If the module cannot be reached the core answers `502 module_unreachable`; on its own timeout `504 upstream_timeout`.',
]],
['h2', '9.3 Module admin endpoint shapes expected'],
['table', ['Module', 'Endpoint', 'Request / response'], [
  ['module-review', '`GET /admin/v1/keys?status=active|used|expired|revoked|all`', 'items `{id, hint, role, note, created_by, created_via, created_at, expires_at, used_at, used_by, revoked_at, status}`'],
  ['module-review', '`POST /admin/v1/keys`', '`{"role", "ttl", "note"}` → `201 {"id", "key", "deep_link", "role", "expires_at"}`; `created_by` from `X-Admin-Actor`'],
  ['module-review', '`DELETE /admin/v1/keys/{id}`', '`204`; `409 key_already_used`; `404`'],
  ['module-review', '`GET /admin/v1/reviewers`, `PATCH|DELETE /admin/v1/reviewers/{id}`', 'as §6.1'],
  ['module-review', '`GET /admin/v1/summaries[/{id}]`, `POST /admin/v1/summaries`', 'as §6.1 (`202` on POST)'],
  ['module-video', '`GET /admin/v1/runs[/{run_id}]`, `GET /admin/v1/prompts`, `POST /admin/v1/golden`, `GET /admin/v1/golden/{id}`', 'as §6.2 (module-video-04, admin endpoints)'],
], [1.2, 2.4, 3]],

['h1', '10. Settings JSON Schema (owner admin-api)'],
['p', 'Embedded in the binary as `internal/settings/schema.json`, published to the core at start (FR-AAPI-081). Values below are the defaults.'],
['code', `{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:manufacture:settings:admin-api:1",
  "type": "object", "additionalProperties": false,
  "properties": {
    "public_origin":            {"type": "string", "format": "uri", "default": "https://admin.example.com"},
    "trusted_proxy_cidrs":      {"type": "array", "items": {"type": "string"}, "default": ["172.16.0.0/12"]},
    "session_idle_timeout":     {"type": "string", "format": "duration", "default": "30m"},
    "session_absolute_timeout": {"type": "string", "format": "duration", "default": "12h"},
    "pending_session_timeout":  {"type": "string", "format": "duration", "default": "10m"},
    "step_up_required":         {"type": "boolean", "default": true},
    "reauth_window":            {"type": "string", "format": "duration", "default": "5m"},
    "totp_skew_steps":          {"type": "integer", "minimum": 0, "maximum": 2, "default": 1},
    "totp_issuer":              {"type": "string", "default": "Manufacture"},
    "recovery_codes_count":     {"type": "integer", "minimum": 5, "maximum": 20, "default": 10},
    "password_min_length":      {"type": "integer", "minimum": 12, "maximum": 64, "default": 12},
    "argon2": {"type": "object", "additionalProperties": false, "default": {},
      "properties": {"memory_kib":  {"type": "integer", "minimum": 19456, "default": 65536},
                     "iterations":  {"type": "integer", "minimum": 2, "default": 3},
                     "parallelism": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1}}},
    "argon2_concurrency":       {"type": "integer", "minimum": 1, "maximum": 16, "default": 4},
    "login_rate_per_ip":        {"type": "integer", "minimum": 1, "default": 10, "description": "per minute"},
    "login_max_failures":       {"type": "integer", "minimum": 3, "default": 5},
    "lockout_duration":         {"type": "string", "format": "duration", "default": "15m"},
    "lockout_max_duration":     {"type": "string", "format": "duration", "default": "24h"},
    "api_rate_reads":           {"type": "integer", "minimum": 10, "default": 300, "description": "per user per minute"},
    "api_rate_writes":          {"type": "integer", "minimum": 5, "default": 60},
    "anonymous_rate_per_ip":    {"type": "integer", "minimum": 5, "default": 30},
    "client_errors_per_session":{"type": "integer", "minimum": 1, "default": 10, "description": "per minute"},
    "invitation_ttl":           {"type": "string", "format": "duration", "default": "72h"},
    "audit_retention_days":     {"type": "integer", "minimum": 90, "default": 400},
    "session_retention_days":   {"type": "integer", "minimum": 1, "default": 30},
    "upstream_timeouts": {"type": "object", "additionalProperties": false, "default": {},
      "properties": {"read": {"type": "string", "default": "5s"}, "write": {"type": "string", "default": "15s"},
                     "module_admin": {"type": "string", "default": "10s"}, "register": {"type": "string", "default": "30s"}}},
    "max_body_bytes":           {"type": "integer", "minimum": 65536, "maximum": 8388608, "default": 1048576},
    "settings_refresh_interval":{"type": "string", "format": "duration", "default": "30s"},
    "grafana_url":              {"type": ["string", "null"], "format": "uri", "default": null}
  }
}`],
['p', 'TOTP is required for every role and is not a setting. `public_origin` has a placeholder default; until it is set, unsafe requests fail the Origin check, so it is set at first deployment (05 §2).'],

['h1', '11. Proposed contract changes'],
['h2', '11.1 To the core and modules (resolved)'],
['p', 'All admin-api proposals are resolved. The core adopted them in core-04 §14 under its own numbers; admin-api keeps its numbering for reference.'],
['table', ['#', 'Proposal', 'Resolution'], [
  ['C1', 'core internal API additions needed by the panel (job detail, presign `disposition`, overview, channel settings schema, `accounts_count`, pipeline `version`/`base_version`, `stats_24h`, `deactivated`, `validation_errors`, rollback `comment`, `PUT /credentials/{id}/value`, `ref`, `last_used_at`, `credential_in_use` with `references`, idea `allowed_actions` and `productions`, embedded variant data, `account_handle`, events `?after=`, retry `{stage, variant_id}` → `{job_id}`, `active_module_id`)', 'resolved: core C25 (core-04 §2)'],
  ['C2', 'settings of `core` and `admin-api` on `/modules/{owner}/settings…`, `PUT /modules/admin-api/settings/schema`', 'resolved: core C26 (§2.14)'],
  ['C3', 'core proxy to module admin endpoints', 'resolved: core C11 (and C24); path `/internal/v1/modules/{id}/admin/v1/{path}`, 8 s core-side timeout (§2.12)'],
  ['C4', '`X-Admin-Actor` and `X-Admin-Actor-Email`', 'resolved: core C14 (§1.3)'],
  ['C5', 'module-review `deep_link`; module-video admin endpoints through the proxy', 'resolved without a core change: module-review returns `deep_link`; module-video uses C11'],
  ['C6', '`Idempotency-Key` on core creates', 'resolved: core §1.6'],
  ['C7', 'problem type `urn:manufacture:problem:<code>`', 'resolved: core C27 (§1.4)'],
  ['C8', 'admin-api bootstrap env `ADMIN_MASTER_KEY`, `OTEL_*`', 'outside the core; to be added to AUTHORING §3 by the owner'],
  ['C9', 'shared list conventions', 'resolved: core C28 (§1.5)'],
], [0.4, 4, 2.1]],
['h2', '11.2 Admin-panel proposals P1–P14'],
['table', ['Panel item', 'Resolution in this document'], [
  ['P1', 'accepted: `POST /auth/setup`, `POST /auth/invite/accept` (both start a pending session), `POST /auth/totp/setup/confirm`, `invite_url` in `POST /users`'],
  ['P2', 'accepted: `/auth/me` shape of §4.2, `POST /auth/session/touch`, `X-Background: 1`'],
  ['P3', 'accepted: `GET|DELETE /auth/sessions`, `POST /auth/password`, `POST /users/{id}/totp/reset`'],
  ['P4', 'accepted: codes of §7 use the panel\'s names (`invalid_code`, `csrf_invalid`, `login_locked`, `totp_required` as 401); `errors[].pointer`'],
  ['P5–P11, P14', 'accepted; provided by the core (C25) under the core\'s names (§5); admin-api passes the fields through and filters `allowed_actions` by permission'],
  ['P10', 'accepted: `/admin-settings`; core settings stay on `/modules/core/settings` as the panel expects'],
  ['P12', 'accepted: module-review returns `deep_link`, admin-api publishes it as `start_link`'],
  ['P13', 'accepted: `POST /client-errors`, metric `admin_panel_client_errors_total{kind}` with a bounded `kind` list'],
  ['Additions for the panel', '`403 reauth_required` and `POST /auth/reauth` for ⇑ operations (setting `step_up_required`, default true): the panel must show a password + code dialog and repeat the request; until it does, an operator may set `step_up_required` to false. `remaining_recovery_codes`, `POST /auth/recovery-codes` and the `/video/*` endpoints exist but have no panel screen yet.'],
], [1.2, 5.3]],

['h1', '12. Versioning and compatibility'],
['ul', [
  'Public API version in the path (`/api/v1`) and in `info.version` of the OpenAPI document (semver). Additive changes (new endpoints, optional fields, new enum values in responses) bump the minor version; the panel ignores unknown fields and shows unknown enum values as text.',
  'Breaking changes need `/api/v2` served side by side until the panel has moved; `oasdiff breaking` in CI enforces this. Deployment order: admin-api first, then the panel.',
  'admin-api tolerates additive changes in the core and module APIs (allowlisting drops unknown fields). A breaking core change is caught by contract tests generated from `core/api/openapi.yaml`.',
  'The settings schema `$id` carries a major version (`…:admin-api:1`); new optional keys with defaults are minor; removing or renaming a key needs a migration of stored values by the core.',
  'Database: owned only by admin-api; no other service may connect to `admin`.',
]],
  ],
};
