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
  ['Time', 'RFC 3339 UTC, e.g. `2026-11-08T14:03:00Z`. Durations as Go duration strings (`30m`, `168h`).'],
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
  ['POST', '`/ideas/{id}/queue`', '`ideas.write`', '`idea.queue`', 'POST `/internal/v1/ideas/{id}/queue`'],
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
  ['GET', '`/modules`, `/modules/{id}`, `/modules/{id}/info`, `/modules/{id}/health`', '`config.read`', '—', 'GET same under `/internal/v1` (`info`, `health` call the module live; class `register`)'],
  ['POST', '`/modules`', '`modules.write`', '`module.register`', 'POST `/internal/v1/modules` (class `register`)'],
  ['PATCH / DELETE', '`/modules/{id}`', '`modules.write`', '`module.update` / `.delete`', 'same'],
  ['POST', '`/modules/{id}/activate`', '`modules.write`', '`module.activate`', 'POST `/internal/v1/modules/{id}/activate`'],
  ['POST', '`/modules/{id}/token`', '`modules.token` ⇑', '`module.token_rotate`', 'POST `/internal/v1/modules/{id}/token`'],
  ['GET', '`/modules/{id}/settings`, `…/schema`, `…/versions`', '`config.read`', '—', 'GET `/internal/v1/modules/{id}/settings…` (`{id}` may be `core`)'],
  ['PUT', '`/modules/{id}/settings`', '`settings.write`', '`module.settings.update`', 'PUT `/internal/v1/modules/{id}/settings`'],
  ['POST', '`/modules/{id}/settings/rollback/{v}`', '`settings.write`', '`module.settings.rollback`', 'POST same under `/internal/v1`'],
  ['GET', '`/admin-settings`, `/admin-settings/schema`, `/admin-settings/versions`', '`config.read`', '—', 'GET `/internal/v1/modules/admin-api/settings…`'],
  ['PUT / POST', '`/admin-settings`, `/admin-settings/rollback/{v}`', '`settings.write`', '`admin.settings.update` / `.rollback`', 'PUT / POST `/internal/v1/modules/admin-api/settings…`'],
  ['GET', '`/credentials`, `/credentials/{id}`', '`credentials.read`', '`credential.read_meta`', 'GET `/internal/v1/credentials`, `/{id}/meta`'],
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
  ['`language`', 'string, read-only', 'set by the core from `default_language` (`en`); never accepted in requests'],
  ['`status`', 'enum `new`|`queued`|`in_production`|`done`|`failed`|`cancelled`', 'read-only'],
  ['`last_production_id`', 'uuid|null', 'read-only'],
  ['`allowed_actions`', 'array of `edit`, `queue`, `delete`', 'core state rules ∩ caller permissions'],
  ['`productions`', 'array `{id, status, started_at, finished_at}`', 'only in `GET /ideas/{id}`'],
  ['`created_by`, `created_at`, `updated_at`', '', 'read-only'],
], [1.6, 2.6, 2.3]],
['p', 'Filters: `status`, `q` (text, notes), `from`, `to` (created_at); sort `created_at`, `priority`. `PATCH` only in status `new` (core `409 conflict` otherwise). `DELETE` needs `ideas.delete` (admin only) and is allowed only while the idea has no productions (core `409 conflict`). `POST /ideas/{id}/queue` moves `new` → `queued`. There are no language fields and no per-idea routing in stage 1.'],
['code', `POST /api/v1/ideas  {"text": "How CREATE DATABASE copies the template in PostgreSQL", "priority": 70, "notes": null}
-> 201 {"id": 42, "text": "…", "language": "en", "priority": 70, "notes": null, "status": "new",
        "last_production_id": null, "allowed_actions": ["edit", "queue", "delete"], "created_by": "owner@example.com", …}`],
['h2', '5.3 Productions and jobs'],
['code', `GET /api/v1/productions?status=running,needs_attention&idea_id=42&channel_id=itim&from=…&to=…
-> {"items": [ProductionSummary], "next_cursor": …}
ProductionSummary = {"id", "idea": {"id", "text"}, "status", "stage", "channel_ids": ["itim"], "started_at", "finished_at", "cost_usd"}

GET /api/v1/productions/{id}  -> ProductionDetail = ProductionSummary + {
  "pipeline_id": "default-v1", "current_position": 2, "trace_id": "0193…",
  "allowed_actions": ["retry:video", "cancel"],
  "provenance": {"commit": "…", "settings_versions": {"video-claude": 7}, "prompt_versions": {…}},
  "variants": [{                                   // exactly one in stage 1
    "id": "0193…", "language": "en", "status": "in_review", "review_round": 2,
    "video": {"ref": "s3://manufacture/<pid>/video/2/final.mp4", "sha256": "…", "duration_s": 58.4,
              "size": 18234112, "width": 1080, "height": 1920, "fps": 30},
    "cover": {"ref": "s3://…"}, "contact_sheet": {"ref": "s3://…"},
    "post": {"caption": "…", "hashtags": ["postgres", "internals"]},
    "checks": {"loudness": {"status": "pass", "value": "-14.1 LUFS"}},
    "changes": "Shortened the intro as requested",
    "review_rounds": [{"round": 1, "decision": "rejected", "reason": "…",
                       "reviewer": {"telegram_user_id": 123, "username": "tim"}, "decided_at": "…"}],
    "publications": [{"platform": "instagram", "platform_account_id": "…", "account_handle": "itim",
                      "external_post_id": "…", "url": "https://…", "published_at": "…", "status": "published", "error": null}]}]}

GET /api/v1/productions/{id}/events?after=1234&limit=200   -> {"items": [{"id": 1235, "type": "job.succeeded", "at": "…", "payload": {…}}], "next_cursor": …}  (ascending)
GET /api/v1/productions/{id}/jobs                           -> {"items": [Job], …}
GET /api/v1/jobs/{id}  -> Job = {"id", "production_id", "stage", "variant_id", "module_id", "attempt", "status",
     "progress": {"percent", "step", "message"}, "settings_version", "started_at", "finished_at", "deadline",
     "metrics": {"cost_usd", "tokens_in", "tokens_out"}, "error": {"class", "message"} | null,
     "input": {…}, "result": {…}, "artifacts": [{"ref", "sha256", "size", "kind"}]}
POST /api/v1/productions/{id}/retry   {"stage": "video", "variant_id": null}  -> 202 {"job_id": "…"}
POST /api/v1/productions/{id}/cancel  {"reason": "duplicate idea"}           -> 202 {ProductionDetail}`],
['p', 'The variant fields come from the canonical `video`, `review` and `publish` stage outputs as stored by the core; `account_handle` is joined by the core. Job `input` and `result` contain credential references (`cred:…`), never values. `allowed_actions` entries `retry:<stage>` and `cancel` are removed for callers without `productions.control`. Status values: production `running`, `needs_attention`, `done`, `failed`, `cancelled`; variant `pending`, `in_video`, `in_review`, `approved`, `publishing`, `published`, `skipped`, `needs_attention`, `failed`, `cancelled`; job `queued`, `dispatched`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`. Unknown values are passed through as strings.'],
['h2', '5.4 Artifacts'],
['code', `GET /api/v1/artifacts/presign?ref=s3://manufacture/0193…/video/2/final.mp4&disposition=inline|attachment
-> 200 {"url": "https://minio.example.com/manufacture/…?X-Amz-…", "expires_at": "2026-11-08T14:18:00Z"}
   400 invalid_ref (not under s3://manufacture/) | 404 not_found`],
['p', 'admin-api checks the `ref` prefix before forwarding; `attachment` makes the URL download with the object\'s file name. URL lifetime is the core setting (default 15 min). The audit row stores the `ref`, not the URL.'],
['h2', '5.5 Stages and pipelines'],
['code', `GET /api/v1/stages -> {"items": [{"id": "video", "name": "Video", "scope": "production", "active_module_id": "video-claude"}, …]}
GET /api/v1/pipelines/default-v1
-> {"id": "default-v1", "name": "Default v1", "is_default": true, "version": 3,
    "stages": [{"position": 1, "stage_id": "video", "scope": "production", "timeout": "90m", "max_attempts": 2, "mode": "single", "merge": null}, …]}
PATCH /api/v1/pipelines/default-v1   {"name": "…", "is_default": true}  -> 200 {Pipeline}
PUT /api/v1/pipelines/default-v1/stages
{"base_version": 3,
 "stages": [{"stage_id": "video",   "timeout": "90m",  "max_attempts": 2, "mode": "single", "merge": null},
            {"stage_id": "review",  "timeout": "168h", "max_attempts": 1, "mode": "single", "merge": null},
            {"stage_id": "publish", "timeout": "30m",  "max_attempts": 3, "mode": "single", "merge": null}]}
-> 200 {Pipeline, "version": 4}    409 version_conflict | 422 validation_failed (invalid order)`],
['p', '`mode` accepts only `single` in stage 1 (`parallel` and `merge` are reserved; the core rejects them).'],
['h2', '5.6 Modules'],
['code', `POST /api/v1/modules
{"id": "publish-social", "name": "Publish (social)", "stage": "publish", "endpoint": "http://module-publish:8080", "enabled": true}
-> 201 {"module": {Module}, "token": "mft_…"}          // token shown once; set as MODULE_CORE_TOKEN of the module
   409 conflict | 422 module_info_invalid | 502 module_unreachable

Module = {"id", "name", "stage", "endpoint", "version", "contract", "enabled", "active",
          "health": "ok|degraded|down|unknown", "last_seen_at", "admin_endpoints": ["/admin/v1/keys"],
          "stats_24h": {"succeeded": 3, "failed": 0}, "created_at", "updated_at"}

POST /api/v1/modules/{id}/activate  -> 200 {"module": {Module}, "deactivated": "review-old" | null}
PATCH /api/v1/modules/{id}  {"name"?, "endpoint"?, "enabled"?}  -> 200 {Module}   409 module_active (disable the active one)
DELETE /api/v1/modules/{id}  -> 204   409 module_active
POST /api/v1/modules/{id}/token  {}   -> 200 {"token": "mft_…"}   (old token invalid at once)
GET  /api/v1/modules/{id}/health     -> 200 {"status": "ok|degraded|down", "latency_ms": 12, "checked_at": "…", "message": null}
GET  /api/v1/modules/{id}/info       -> 200 {canonical /info body}`],
['p', 'Token fields are never stored or logged by admin-api and are masked in audit rows.'],
['h2', '5.7 Module, core and admin-api settings'],
['code', `GET /api/v1/modules/video-claude/settings
-> 200 SettingsVersion = {"module_id": "video-claude", "version": 7, "values": {…}, "author": "owner@example.com",
        "comment": "…", "created_at": "…", "is_current": true,
        "validation_errors": [{"pointer": "/render/timeout", "message": "…"}]}   // non-empty after a schema change
GET /api/v1/modules/video-claude/settings/schema   -> 200 {JSON Schema 2020-12}
PUT /api/v1/modules/video-claude/settings  {"base_version": 7, "values": {…}, "comment": "longer render timeout"}
-> 201 {SettingsVersion, "version": 8}
   409 version_conflict {"current_version": 8, "author": "…", "saved_at": "…"} | 422 validation_failed (errors[] with pointers)
GET /api/v1/modules/video-claude/settings/versions?limit=20  -> {"items": [SettingsVersion], …}   (values included)
POST /api/v1/modules/video-claude/settings/rollback/5  {"comment": "back to 5"}  -> 201 {SettingsVersion, "version": 9}`],
['p', 'The core\'s own settings use module id `core` on the same endpoints. admin-api\'s own settings use `/admin-settings`, `/admin-settings/schema`, `/admin-settings/versions`, `/admin-settings/rollback/{v}` with the same shapes (`module_id` = `admin-api`); after a successful save admin-api refreshes its snapshot at once.'],
['h2', '5.8 Credentials'],
['code', `GET /api/v1/credentials?kind=oauth_token&q=insta
-> {"items": [CredentialMeta], "next_cursor": null}
CredentialMeta = {"id": "0192…", "name": "instagram-itim", "ref": "cred:instagram-itim", "kind": "oauth_token",
                  "last4": "x9Qa", "expires_at": "2027-01-05T00:00:00Z", "allowed_modules": ["publish-social"],
                  "created_at": "…", "updated_at": "…", "last_used_at": "…"}
POST  /api/v1/credentials  {"name": "anthropic-main", "kind": "api_key", "value": "<secret>", "expires_at": null, "allowed_modules": ["video-claude"]}
-> 201 {CredentialMeta}
PUT   /api/v1/credentials/{id}  {"value": "<secret>", "expires_at": "2027-01-05T00:00:00Z"}  -> 200 {CredentialMeta}
PATCH /api/v1/credentials/{id}  {"allowed_modules": [...], "expires_at": …}  -> 200 {CredentialMeta}
DELETE /api/v1/credentials/{id} -> 204
   409 credential_in_use {"references": [{"type": "platform_account", "id": "…"}, {"type": "module_settings", "id": "video-claude"}]}`],
['p', '`name` is a slug of 2–64 characters. `kind` ∈ `api_key`, `oauth_token`, `bot_token`, `password`. `value` is `writeOnly` and `x-secret`, 1–16 384 bytes; no response contains it, and admin-api does not decode a field named `value` from any credential response.'],
['h2', '5.9 Overview'],
['code', `GET /api/v1/overview
-> 200 {"counts": {"ideas_queued": 3, "productions_running": 1, "waiting_review": 1, "published_today": 2, "failed_24h": 0},
        "active": [{"production_id": "…", "idea": {"id": 42, "text": "…"}, "status": "running", "stage": "video",
                    "progress": {"percent": 40, "step": "render"}, "started_at": "…"}],
        "waiting_review": [{"production_id": "…", "variant_id": "…", "idea_text": "…", "round": 2, "since": "…"}],
        "modules": [{"stage": "video", "module_id": "video-claude", "health": "ok", "last_seen_at": "…"}],
        "alerts": [{"kind": "credential_expiring", "severity": "warning", "message": "…",
                    "resource": "credential", "resource_id": "…", "at": "…"}],
        "publications_today": [{"production_id": "…", "platform": "instagram", "account_handle": "itim",
                                "url": "https://www.instagram.com/reel/…", "published_at": "…"}]}`],
['p', 'Alert `kind`: `production_failed`, `needs_attention`, `review_waiting`, `module_unhealthy`, `credential_expiring`, `credential_expired`, `publish_failed`, `budget_exceeded`. The whole object is computed by the core; if the core is down admin-api returns `503 upstream_unavailable`.'],

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
  ['409', '`conflict`, `email_taken`, `last_admin`, `setup_not_available`, `version_conflict`, `module_active`, `credential_in_use`, `module_not_available`, `module_capability_missing`', 'state conflicts; no active module for the stage; module lacks the admin endpoint'],
  ['410', '`token_used`, `token_expired`', 'setup or invitation link'],
  ['412', '`precondition_failed`', '`If-Match` mismatch'],
  ['413', '`payload_too_large`', 'body over `max_body_bytes`'],
  ['422', '`validation_failed`, `cannot_modify_self`, `module_info_invalid`', 'schema or business validation with `errors[]`; password codes in `errors[].code`: `password_too_short`, `password_too_common`, `password_matches_identity`'],
  ['429', '`rate_limited`, `login_locked`', 'with `Retry-After`'],
  ['500', '`internal`', 'bug; details only in logs'],
  ['502', '`upstream_error`, `module_unreachable`', 'core answered 5xx, 401/403 to admin-api, or an undecodable body; module unreachable from the core relay'],
  ['503', '`upstream_unavailable`, `audit_unavailable`, `busy`', 'core not reachable; audit store down; password hashing queue full; with `Retry-After`'],
  ['504', '`upstream_timeout`', 'upstream exceeded its timeout class'],
], [0.8, 3, 2.8]],

['h1', '8. Internal endpoints (not routed by the proxy)'],
['table', ['Endpoint', 'Response'], [
  ['`GET /health`', '`200 {"status": "ok"}`; `503` while draining'],
  ['`GET /ready`', '`200 {"status": "ready", "db": "ok", "migrations": 5, "core": "ok|down", "settings_version": 3}`; `503` if the DB fails'],
  ['`GET /metrics`', 'Prometheus text format, metrics of 03 §8.1'],
], [1.5, 5]],

['h1', '9. Consumed interfaces'],
['h2', '9.1 Core internal API'],
['p', 'Base `ADMIN_CORE_URL` + `/internal/v1`. Headers on every call: `Authorization: Bearer <ADMIN_CORE_TOKEN>`, `traceparent`, `X-Request-Id`, `X-Admin-Actor: <user id>` and `X-Admin-Actor-Email: <e-mail>` (absent for system calls such as settings refresh), `X-Production-Id` for production, job and artifact calls, `Idempotency-Key` and `If-Match` when the client sent them. The core answers RFC 9457 problems with the same `code` vocabulary for client errors.'],
['table', ['Core endpoint', 'Used by', 'Status'], [
  ['`GET|POST /brands`, `GET|PATCH /brands/{id}`', 'brands', 'draft core §8'],
  ['`GET|POST /channels`, `GET|PATCH|DELETE /channels/{id}`', 'channels', 'draft core §8'],
  ['`GET /channels/settings-schema`; `accounts_count` in Channel', 'channel settings form', 'proposed C1'],
  ['`GET|POST /platform-accounts`, `GET|PATCH|DELETE /platform-accounts/{id}`', 'accounts', 'draft core §8'],
  ['`GET|POST /routing-rules`, `PATCH|DELETE /routing-rules/{id}`', 'routing', 'draft core §8'],
  ['`GET|POST /ideas`, `GET|PATCH|DELETE /ideas/{id}`, `POST /ideas/{id}/queue`; `allowed_actions`, `productions` in idea detail', 'ideas', 'draft core §8; additions C1'],
  ['`GET /productions`, `GET /productions/{id}` (embedded variant data, `allowed_actions`), `…/events?after=`, `…/jobs`, `POST …/retry {stage, variant_id}`, `POST …/cancel`', 'productions', 'draft core §8; additions C1'],
  ['`GET /jobs/{id}`', 'job detail', 'proposed C1'],
  ['`GET /artifacts/presign?ref=&disposition=`', 'artifacts', 'proposed C1'],
  ['`GET /stages` (with `active_module_id`), `GET|POST /pipelines`, `GET|PATCH /pipelines/{id}`, `PUT /pipelines/{id}/stages` with `base_version`', 'stages, pipelines', 'draft core §8; additions C1'],
  ['`GET|POST /modules`, `GET|PATCH|DELETE /modules/{id}`, `POST …/activate` (`deactivated`), `GET …/health`, `GET …/info`, `POST …/token`; `stats_24h`', 'modules', 'draft core §8; additions C1'],
  ['`GET|PUT /modules/{id}/settings` (`validation_errors`, `base_version`), `GET …/schema`, `GET …/versions`, `POST …/rollback/{v}` (`comment`), for `{id}` = any module, `core`, `admin-api`; `PUT /modules/admin-api/settings/schema`', 'module, core and admin-api settings', 'draft core §8; owner `admin-api` and schema PUT proposed C2'],
  ['`GET|POST /credentials`, `GET /credentials/{id}/meta`, `PUT /credentials/{id}/value`, `PATCH|DELETE /credentials/{id}` (`credential_in_use`); `ref`, `last_used_at`', 'credentials', 'draft core §8; additions C1'],
  ['`GET /overview`', 'overview', 'proposed C1'],
  ['`ANY /modules/{id}/admin/{path}`', 'module admin relay', 'proposed C3'],
  ['`GET /health`', 'readiness detail', 'core standard'],
], [3.6, 1.3, 1.6]],
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
['h2', '11.1 To the core and modules'],
['table', ['#', 'Proposal', 'Affects', 'Why'], [
  ['C1', 'Core internal API additions needed by the panel: `GET /jobs/{id}`, `GET /artifacts/presign` (`disposition`), `GET /overview` (shape of §5.9), `GET /channels/settings-schema`, `Channel.accounts_count`, `GET|PATCH /pipelines/{id}` with `version` and `base_version` on `PUT …/stages`, `GET /modules/{id}/info`, `POST /modules/{id}/token`, `Module.stats_24h`, activate response `deactivated`, `validation_errors` and `base_version` on settings, rollback body `comment`, `PUT /credentials/{id}/value`, `CredentialMeta.ref` and `last_used_at`, `409 credential_in_use` with `references`, `Idea.allowed_actions` and `productions`, `ProductionDetail` with embedded variant data, `account_handle` and `allowed_actions`, events `?after=`, retry body `{stage, variant_id}` → `{job_id}`, `GET /stages` with `active_module_id`', 'core-04', 'carried from admin-panel-04 §13 P5–P11, P14; admin-api passes them through'],
  ['C2', 'Settings endpoints `/internal/v1/modules/{id}/settings…` also serve owner `admin-api` (as for `core`), plus `PUT /internal/v1/modules/admin-api/settings/schema` to register its schema', 'core-04', 'system rule: admin-api settings live in the core'],
  ['C3', 'Core proxy `ANY /internal/v1/modules/{id}/admin/{path}` (agreed with module-review, its P3): admin-api uses `ADMIN_CORE_TOKEN`; the core checks `admin_endpoints` from `/info`, forwards with the module token and passes `X-Admin-Actor`', 'core-04, module-review-04, module-video-04', 'modules verify one caller (the core); admin-api holds no module secrets. The core must keep module tokens recoverable (encrypted) to send them, not only hashed'],
  ['C4', 'Header `X-Admin-Actor: <user id>` (as agreed with module-review) plus optional `X-Admin-Actor-Email` on admin-api → core calls; the core uses them as `author` of settings versions and `created_by` of ideas and passes `X-Admin-Actor` on through the module proxy', 'core-04', 'authorship without the core knowing panel users'],
  ['C5', 'module-review `POST /admin/v1/keys` returns `deep_link` (published by admin-api as `start_link`); module-video `/admin/v1/runs`, `/prompts`, `/golden` reached through the core proxy (answers module-video PC5)', 'module-review-04, module-video-04', 'panel P12; one way for admin-api to reach every module'],
  ['C6', 'Optional `Idempotency-Key` on core `POST` creates, deduplicated 24 h', 'core-04', 'safe resubmits from the panel'],
  ['C7', 'Problem `type` URIs `urn:manufacture:problem:<code>` for all services; codes of §7 shared where they apply', 'all 04 documents', 'stable identifiers without a domain'],
  ['C8', 'Bootstrap env for admin-api extended with `ADMIN_MASTER_KEY` (optional `ADMIN_MASTER_KEY_PREVIOUS`) and standard `OTEL_*` variables', 'AUTHORING §3', 'TOTP secrets must be encrypted at rest by admin-api'],
  ['C9', 'Core lists use the conventions of §1 (`limit`, `cursor`, `next_cursor`, `from`/`to`) so admin-api passes cursors through unchanged', 'core-04', 'no re-paging in admin-api'],
], [0.4, 3.4, 1.2, 2]],
['h2', '11.2 Admin-panel proposals P1–P14'],
['table', ['Panel item', 'Resolution in this document'], [
  ['P1', 'accepted: `POST /auth/setup`, `POST /auth/invite/accept` (both start a pending session), `POST /auth/totp/setup/confirm`, `invite_url` in `POST /users`'],
  ['P2', 'accepted: `/auth/me` shape of §4.2, `POST /auth/session/touch`, `X-Background: 1`'],
  ['P3', 'accepted: `GET|DELETE /auth/sessions`, `POST /auth/password`, `POST /users/{id}/totp/reset`'],
  ['P4', 'accepted: codes of §7 use the panel\'s names (`invalid_code`, `csrf_invalid`, `login_locked`, `totp_required` as 401); `errors[].pointer`'],
  ['P5–P11, P14', 'accepted and forwarded to the core as C1; admin-api passes the fields through and filters `allowed_actions` by permission'],
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
