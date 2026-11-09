# core API contract files

`openapi.yaml` and `../schemas/` are machine-readable extracts of
`docs/core/core-04-contracts.docx` (source: `docs/tools/specgen/content/core/core-04-contracts.js`).
core-04 is authoritative; when they differ, fix this folder.

Check them with:

```bash
cd docs/tools/contractcheck && npm ci && npm test
```

## Coverage of openapi.yaml (initial, intentionally incomplete)

Covered: `/health`, `/ready`, module callbacks (core-04 §3), module reads and writes (§4).

Not covered yet (core-04 §2, admin-api principal):

- [ ] §2.1 brands, §2.2 channels (+ `/channels/settings-schema`), §2.3 platform accounts
- [ ] §2.4 routing rules and `/routing/resolve`, §2.5 idea routing overrides
- [ ] §2.6 ideas (+ queue, unqueue), §2.7 productions and variant actions, §2.8 events, §2.9 jobs
- [ ] §2.10 stages, §2.11 pipelines (C34 `If-Match` on `PUT .../stages`), §2.12 modules and admin proxy
- [ ] §2.13-2.14 settings, §2.15 credentials meta, §2.16 artifacts presign and overview
- [x] C38 admin republish `POST /internal/v1/publish-intents/{id}/republish` (D18 accepted)

## Schemas

- `schemas/*.json`: module contract 1 (§7) and stage outputs (§8), with optional fields of proposed changes C31, C37-C39 marked in `description`.
- `schemas/stage-metadata-output.json`: proposed stage `metadata` (C39, P1); not seeded until accepted.
- `schemas/events/*.json`: RabbitMQ envelope and payloads (§15, proposed C29-C31).
- `schemas/examples/cases.json`: examples with expected validity (valid and invalid cases).

## Added in registry-credentials-prompts

- Admin: `POST /modules`, `POST /modules/{id}/token`, `POST /modules/{id}/activate`
- Module: `POST /modules/self/heartbeat` (updates `last_seen_at`)
- Credentials GET already listed; implementation wired
- Prompts: no core HTTP and no core table (D16/C40: module-video owns storage); core ships `internal/prompts` substitution helper only
