# admin-panel

Веб-клиент локальной админки Manufacture (D24). **Без входа.** Только localhost, same-origin с `admin-api`.

Интерфейс на русском. Стек: React 19, TypeScript (strict), Vite, TanStack Router, TanStack Query, Mantine, клиент `openapi-fetch` по схеме admin-api.

## Как открыть

После `./deploy/up.sh` панель раздаётся самим admin-api (без отдельного nginx):

**http://127.0.0.1:58084/**

Это тот же origin, что и `/api/v1`, поэтому allowlist `Host`/`Origin` не ломается.

## Разработка

```bash
cd admin-panel
npm ci
npm run gen:api          # src/api/schema.d.ts из admin-api/api/openapi.yaml
npm run dev              # http://127.0.0.1:5173, proxy /api /health /ready → admin-api
```

`ADMIN_API_PROXY` (только dev-сервер Vite, в бандл не попадает) указывает, куда проксировать, по умолчанию `http://127.0.0.1:58084`. Можно сгенерировать типы с живого шлюза:

```bash
npx openapi-typescript http://127.0.0.1:58084/api/v1/openapi.json -o src/api/schema.d.ts
```

В репозитории источником истины остаётся YAML; `GET /api/v1/openapi.json` отдаёт тот же документ.

## Проверки

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

После изменения `admin-api/api/openapi.yaml` выполните `npm run gen:api` и закоммитьте `src/api/schema.d.ts`. CI сверяет, что файл не расходится со схемой.

## Что в этом PR

Каркас: лейаут, сайдбар, тема, индикатор связи, типизированный клиент, обработка problem+json. Живой экран — **Обзор** (модули и счётчики). Остальные разделы — заглушки до следующих PR.
