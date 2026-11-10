# admin-panel — context for agents

React 19 + TypeScript strict + Vite + TanStack Router/Query + Mantine; UI text is **Russian**. API client `openapi-fetch` generated from `admin-api/api/openapi.yaml` into `src/api/schema.d.ts`
(regenerate with `npm run gen:api` and commit; CI fails on drift). Served by admin-api at `http://127.0.0.1:58084/` (same origin).
Screens (`src/pages`): Overview, Productions, Review & publications, Accounts & credentials, Prompts, Audit log, Ideas & topics (shows "module-video does not support this yet" on 404).
Checks: `npm ci && npm run lint && npm run typecheck && npm test && npm run build`. Dev: `npm run dev` (proxy via `ADMIN_API_PROXY`).
