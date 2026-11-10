# admin-api — context for agents

Go gateway for the local admin panel (D24). **No login**; localhost only (`127.0.0.1:58084` in Compose). Host/Origin allowlist (`localhost`, `127.0.0.1`, `[::1]`), no CORS headers.
Acts as `X-Admin-Actor: local:admin` against core (`mfa_…` admin token) and `X-Actor: local:admin` + module bearer tokens (`MODULE_TOKEN_{VIDEO,REVIEW,PUBLISH}`) against modules.

- `cmd/admin-api`, `internal/httpapi` (`server.go` routes under `/api/v1`: overview, modules, productions, jobs cancel, variants retry/skip, publish-intents republish, audit, per-module secrets/accounts/prompts proxies; `static.go` serves the SPA from `ADMIN_UI_DIR`; `openapi.go` serves `/api/v1/openapi.json`),
  `internal/upstream` (clients of core and modules), `internal/audit` + `internal/db/migrations` (own `admin` DB, `audit_log`), `internal/problem` (problem+json), `internal/bootstrap`.
- Source of truth for the API: `api/openapi.yaml` (the panel generates TypeScript types from it; CI checks drift). Missing video routes (ideas/topics): `docs/VIDEO_ADMIN_ROUTES.md`.
- Secrets: write allowed, read returns only present/updated_at — never values or lengths.
```bash
docker run --rm -v $PWD/..:/src -v mf-gomod:/go/pkg/mod -w /src/admin-api golang:1.26-bookworm go test ./...
```
