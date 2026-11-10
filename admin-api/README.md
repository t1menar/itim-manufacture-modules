# admin-api

Единая точка для локальной админ-панели (D24). **Без входа.** Слушает только loopback: нативно `127.0.0.1:8080`, в Compose порт публикуется как `127.0.0.1:58084`.

Защита localhost: `Host` (и `Origin`, если он есть) только из allowlist `localhost` / `127.0.0.1` / `[::1]`. Заголовков CORS нет (в том числе нет `*`).

## Запуск

```bash
./deploy/up.sh
curl -sS http://127.0.0.1:58084/health
curl -sS http://127.0.0.1:58084/api/v1/overview
```

В контейнере процесс слушает `0.0.0.0:8080`, наружу — только `127.0.0.1`. Healthchecks внутри сети ходят на `/health` (Host-проверка для `/health` и `/ready` отключена).

Переменные: `ADMIN_DATABASE_URL`, `CORE_URL`, `MODULE_CORE_ADMIN_TOKEN` или `CORE_ADMIN_TOKEN` (`mfa_`), `MODULE_TOKEN_{VIDEO,REVIEW,PUBLISH}` (`mft_`), опционально `VIDEO_URL` / `REVIEW_URL` / `PUBLISH_URL`. Адреса модулей также читаются из реестра core.

Актор: `X-Admin-Actor: local:admin` к core; к модулям ещё `X-Actor: local:admin`. Модули проверяют bearer `MODULE_CORE_TOKEN`.

OpenAPI: `GET /api/v1/openapi.json`, исходник `admin-api/api/openapi.yaml`.

Контракт недостающих роутов video (идеи/темы): [`docs/VIDEO_ADMIN_ROUTES.md`](docs/VIDEO_ADMIN_ROUTES.md).

## Панель

Если задан `ADMIN_UI_DIR` (в образе `/ui`), admin-api раздаёт собранный `admin-panel` с того же origin: `GET /` — SPA, `/api/v1` — API. Host/Origin allowlist применяется и к статике.
