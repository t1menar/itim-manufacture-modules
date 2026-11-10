# Контракт admin-роутов module-video, которых ещё нет

Код `module-video` в этом PR **не меняется**. admin-api уже проксирует перечисленные пути на активный video-модуль (`Authorization: Bearer <MODULE_CORE_TOKEN / mft_>`, заголовок `X-Actor: local:admin`). Пока роутов нет, панель получит ответ модуля (обычно 404) или `503 upstream_unavailable`, если модуль недоступен.

Аутентификация как у существующих `/admin/v1/prompts` и `/admin/v1/credentials`: bearer `MODULE_CORE_TOKEN`.

Ошибки: `application/problem+json` (`code`, `title`, `status`). Секреты в ответах запрещены.

Идеи живут только в БД video (D21): статусы `draft` → `ready` → `queued` → `dispatched` → `in_production` → `done`/`failed` (плюс cancelled/archived). См. `video-modules/module-video/docs/IDEAS.md`.

## Темы

| Метод | Путь | Тело / заметки |
|-------|------|----------------|
| `GET` | `/admin/v1/topics` | список `{items:[{id,code,title,description,default_tags,default_platforms,active}]}` |
| `POST` | `/admin/v1/topics` | `{code,title,description?,default_tags?,default_platforms?,active?}` → `201` |
| `GET` | `/admin/v1/topics/{id}` | одна тема |
| `PATCH` | `/admin/v1/topics/{id}` | частичное обновление |
| `DELETE` | `/admin/v1/topics/{id}` | `204`; конфликт, если есть живые идеи (`409`) |

## Идеи

| Метод | Путь | Тело / заметки |
|-------|------|----------------|
| `GET` | `/admin/v1/ideas` | фильтры `status`, `topic_id`, `limit`, `cursor`; `{items,next_cursor}` |
| `POST` | `/admin/v1/ideas` | `{topic_id,title,description?,hook?,language?,priority?,tags?,author?}` статус `draft`, `201` |
| `GET` | `/admin/v1/ideas/{id}` | полная идея + `rev` |
| `PATCH` | `/admin/v1/ideas/{id}` | правка в `draft` (или согласованных статусах); optimistic `If-Match` / `rev` по желанию |
| `DELETE` | `/admin/v1/ideas/{id}` | только без живой production; иначе `409` |
| `POST` | `/admin/v1/ideas/{id}/ready` | `draft` → `ready` (`ready_at=now()`) |
| `POST` | `/admin/v1/ideas/{id}/queue` | `ready` → `queued` (`queued_at=now()`); шедулер публикует `idea.ready` |

Публичные пути admin-api: `/api/v1/topics…` и `/api/v1/ideas…` (1:1 на таблицу выше).

## Уже есть в module-video (проксируются)

- `GET/PUT/DELETE /admin/v1/credentials` (значение write-only)
- `GET/POST /admin/v1/prompts…`, `PUT /admin/v1/prompts/{step}/active`, `GET /admin/v1/prompts/audit`
