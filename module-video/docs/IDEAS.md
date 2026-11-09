# Идеи и темы в module-video (D21)

_Статус: спецификация. Реализацию шедулера и изменения core этот документ не делает._  
_Дата: 2026-11-09 (Europe/Stockholm)._

## 1. Решение

Все идеи роликов и справочник тем живут **только** в БД `video` (module-video).  
Core свою таблицу `ideas` **депрекейт** и больше не является источником бэклога.

Поток MVP:

1. Админ заводит тему и идею **прямо в БД** (admin-api нет; Telegram-бот только для ревью).
2. Шедулер **в module-video** выбирает готовые идеи и публикует `idea.ready` в RabbitMQ topic exchange через transactional outbox.
3. Core потребляет `idea.ready` (inbox dedup), создаёт production со **снимком** идеи и дальше гоняет pipeline как сейчас.
4. Core сообщает обратные статусы идее (`in_production` / `done` / `failed`), чтобы шедулер не слал её снова.

## 2. Что уже есть (на `origin/main`)

### 2.1 module-video

| Что | Где | Замечание |
|-----|-----|-----------|
| Вход job `input.idea {id, text, language}` | `contract.Idea`, `intake.py` | `language` обязан быть `en`, иначе 422 `language_unsupported` |
| Схемы артефактов с «topic» | `validate/schemas/analysis.schema.json` (`topic` string), `post.schema.json` (`topic_hashtags`) | Это **выход анализа/поста**, не справочник тем |
| `metadata.topics[]` в результате ролика | `contract.Metadata` (D19) | Теги ролика, не FK на тему |
| БД `runs` / `steps` / prompts | `db/models.py`, миграции `0001`–`0003` | Таблиц `ideas` / `topics` **нет** |
| Golden-набор идей | спека `golden/ideas.json` | Фикстуры прогонов, не бэклог |

Итого: пайплайн ролика уже умеет принимать идею, но **владение бэклогом идей в модуле ещё не реализовано**. Ниже — целевой контракт; расхождения с кодом — в §8.

### 2.2 core (текущее поведение, будет заменено)

| Что | Где |
|-----|-----|
| Таблица `ideas` (`text`, `language`, `priority`, `status`, `pipeline_id`, `rev`, …) | `migrations/0001_init.sql` |
| Шедулер `Engine.Tick`: `queued` → production, `FOR UPDATE SKIP LOCKED`, advisory lock | `engine/engine.go` |
| Job input | `{"idea":{"id","text","language"}}` |
| Антидубль production | `UNIQUE (idea_id, run_no)`, `productions_live_uq (idea_id) WHERE status = 'running'` |
| Messaging | exchanges `manufacture.commands` / `manufacture.events` (topic), outbox UUID `message_id`, inbox `(consumer, message_id)` |

## 3. Владение данными

| Сущность | Владелец | Core |
|----------|----------|------|
| `topics`, `ideas`, outbox шедулера | БД `video` | не хранит |
| Production / jobs / variants | БД `core` | **снимок** идеи в production (`idea_snapshot` jsonb) + `idea_ref` |
| Маршрутизация каналов, pipeline | core | без изменений |

Редактирование идеи после `dispatched` не меняет уже ушедший снимок: только новый `rev` и новая отправка (если статус позволяет).

## 4. Модель

### 4.1 Тема (`topics`)

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `id` | bigint identity PK | |
| `code` | text | unique, `^[a-z][a-z0-9_]{1,63}$` |
| `title` | text | 1…120 |
| `description` | text | null / ≤4000 |
| `default_tags` | text[] | без `#`, элементы `^[a-z0-9_]{2,40}$`, ≤20 |
| `default_platforms` | text[] | напр. `{instagram}`, ≤8 |
| `active` | boolean | default true |
| `rev` | int | ≥1, default 1 |
| `created_at` / `updated_at` | timestamptz | |

Неактивную тему нельзя назначать новым идеям (`ready`).

### 4.2 Идея (`ideas`)

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `id` | bigint identity PK | стабильный id; в job/core уходит как `idea.id` |
| `topic_id` | bigint FK → topics | обязателен |
| `title` | text | 1…200 |
| `description` | text | 1…4000 — развёрнутое ТЗ для анализа |
| `hook` | text | null / ≤300 — угол / хук |
| `audience` | text | null / ≤500 |
| `tags` | text[] | без `#`; если пусто — взять `topics.default_tags` при снимке |
| `references` | jsonb | массив `{url, note?}`, ≤20 |
| `constraints` | jsonb | `{duration_s?, format?, notes?}` |
| `language` | text | MVP: только `en` |
| `priority` | int | −100…100, default 0 |
| `notes` | text | null / ≤2000, внутренние |
| `author` | text | null / `tg:<id>` или `db:<user>` |
| `pipeline_id` | text | null → default pipeline в core |
| `status` | text | см. §4.3 |
| `rev` | int | ≥1; +1 при любом изменении контента или `ready`→отправка |
| `ready_at` | timestamptz | null; ставится при переходе в `ready` |
| `dispatched_at` | timestamptz | null |
| `last_message_id` | uuid | null; UUID outbox/`idea.ready` |
| `failure` | jsonb | null / `{code, message?}` |
| `created_at` / `updated_at` | timestamptz | |

Индекс очереди: `(priority DESC, ready_at, id) WHERE status = 'ready'`.

Контент-поля (title…constraints, topic_id, language, pipeline_id) меняются только в `draft` / `ready`.  
`priority` и `notes` — также в `failed` / `cancelled` (чтобы переставить в очереди после возврата в `ready`).

### 4.3 Статусы идеи

```
draft → ready → dispatched → in_production → done
                 ↓                ↓
              cancelled         failed → ready   (после правки / retry)
ready → draft | cancelled
done | failed | cancelled → archived
```

| Статус | Смысл |
|--------|--------|
| `draft` | черновик, шедулер игнорирует |
| `ready` | готова к отправке |
| `dispatched` | `idea.ready` записан в outbox (эту `rev` повторно не шлём) |
| `in_production` | core принял и создал live production |
| `done` / `failed` / `cancelled` / `archived` | терминальные / архив |

Переход `ready` → `dispatched` — **только** в одной транзакции с INSERT в outbox (§5).

## 5. Шедулер

### 5.1 Где живёт — **в module-video**

Обоснование:

1. Бэклог и `SKIP LOCKED` — в БД `video`; dual-write в core запрещён.
2. Смена статуса и outbox должны быть одной транзакцией (как у core для jobs).
3. Core остаётся потребителем события и владельцем production, без опроса чужой БД.
4. Сообщение пользователя: шедулер «собирает идеи из первого модуля и отправляет в топик».

Core-`Tick` по таблице `ideas` **удаляется / депрекейтится** после миграции.

### 5.2 Цикл

1. Если settings `ideas.scheduler.paused` — выход.
2. `pg_advisory_xact_lock(hashtext('video.ideas.scheduler'))`.
3. Лимит: `ideas.scheduler.max_dispatch_per_tick` (default 5) и глобальный `ideas.scheduler.max_in_flight` (считаем `dispatched`+`in_production`; default = core `max_concurrent_productions` или 2).
4. `SELECT … FROM ideas WHERE status = 'ready' AND topic активен ORDER BY priority DESC, ready_at, id LIMIT n FOR UPDATE SKIP LOCKED`.
5. Для каждой: собрать снимок (§6), `rev` уже зафиксирован; `message_id = UUIDv5(ns, 'idea:'||id||':v'||rev)`; INSERT outbox; `status = dispatched`, `dispatched_at = now()`, `last_message_id = message_id`.
6. Relay outbox → exchange `manufacture.events`, routing key `idea.ready` (или `idea.ready.video`).

Интервал тика: settings `ideas.scheduler.tick_s` (default 5) + опционально `NOTIFY video_ideas`.

### 5.3 Гарантия «не слать повторно»

| Слой | Механизм |
|------|----------|
| Publisher БД | переход `ready`→`dispatched` только из `ready`; partial unique: одна pending/sent outbox-строка на `(idea_id, rev)` / `message_id` UNIQUE |
| Стабильный id | `message_id = UUIDv5(URL_NS, "idea:<id>:v<rev>")` — совместим с uuid-inbox core; бизнес-ключ `idea_ref = "idea:<id>:v<rev>"` в payload |
| Consumer | core inbox `(consumer, message_id)` → повторный delivery = no-op |
| Production | `UNIQUE` live production на `idea_id` (как сейчас `productions_live_uq`); плюс уникальность принятого `idea_ref` (или `(idea_id, idea_rev)`), чтобы тот же снимок не создал второй run |

Повторная постановка: только `failed`/`cancelled`/`done`(редко) → правка при необходимости → снова `ready` с **новым** `rev`.

## 6. Контракт JSON

Канонические схемы: `contracts/topic.json`, `contracts/idea.json`, `contracts/events/idea.ready.json`.

### 6.1 Снимок идеи (тело идеи в событии и в job)

```json
{
  "id": 42,
  "rev": 3,
  "idea_ref": "idea:42:v3",
  "title": "CREATE DATABASE copies a template",
  "description": "Show that CREATE DATABASE in PostgreSQL copies template1; explain three surprises.",
  "hook": "CREATE DATABASE creates nothing. It copies.",
  "audience": "backend engineers who use Postgres daily",
  "language": "en",
  "tags": ["postgresql", "databases"],
  "references": [{"url": "https://www.postgresql.org/docs/current/manage-ag-templatedbs.html", "note": "template DBs"}],
  "constraints": {"duration_s": 160, "format": "reel"},
  "priority": 10,
  "pipeline_id": null,
  "topic": {
    "id": 7,
    "code": "postgres_internals",
    "title": "PostgreSQL internals",
    "default_tags": ["postgresql", "backend"],
    "default_platforms": ["instagram"],
    "rev": 1
  }
}
```

`text` для обратной совместимости job input (пока module-video `Idea.text` обязателен):

- `text = title` если `description` пусто не бывает; рекомендуется `text = title`, а полное ТЗ — в `description` (расширение input, §7).

### 6.2 Событие `idea.ready`

Envelope как в `core/schemas/events/envelope.json`, расширенный тип:

- `type`: `idea.ready`
- `producer`: `module:video`
- `message_id`: UUID v5 (§5.3)
- `payload`: снимок §6.1 (+ опционально `queued_channels_hint` не требуется — routing остаётся в core)

Core queue bind: `idea.#` на `manufacture.events` (рядом с текущим `job.#`).

### 6.3 Обратные статусы (core → module-video)

Минимум для MVP — HTTP callback или событие `idea.status` в `manufacture.commands` / `manufacture.events`:

| Событие core | Статус идеи |
|--------------|-------------|
| production создан | `in_production` |
| production `done` | `done` |
| production `failed` / idea `no_route`/`no_pipeline` | `failed` + `failure` |

Идемпотентность: по `idea_ref` / `(idea_id, rev)`; поздний статус не откатывает более «поздний» (монотонность: dispatched < in_production < done|failed).

Пока обратный канал не сделан, допустим временный poll/admin SQL — зафиксировать в §9.

## 7. Что меняется в core (только план)

1. Депрекейт таблицы `ideas` и `Engine.Tick` по ней; вместо этого consumer `idea.ready`.
2. `productions`: `idea_id` (bigint, id из модуля) + `idea_rev` + `idea_ref` text + `idea_snapshot` jsonb NOT NULL; FK на core.`ideas` убрать.
3. Job `input.idea` расширить полями снимка (title, description, hook, audience, tags, references, constraints, topic, rev, idea_ref); оставить `id`/`text`/`language` для совместимости (`text` ← `title`).
4. Схему `job-request.json` и envelope enum — добавить `idea.ready`.
5. Уникальности: сохранить «один live production на idea_id»; добавить защиту от повторного apply того же `idea_ref`.

Реализацию в этом PR **не делать**.

## 8. Что добавить в module-video (владельцу модуля)

1. Миграция: таблицы `topics`, `ideas`, `outbox` (или общий outbox модуля), inbox для обратных статусов.
2. JSON Schema / pydantic-модели темы и идеи; отдать снимок в job intake (расширить `contract.Idea` или отдельный `IdeaSnapshot`).
3. Шедулер + outbox relay (AMQP), settings `ideas.scheduler.*`.
4. Админ на MVP: SQL-скрипты / seed в README (примеры INSERT); HTTP admin API идей — позже.
5. Обработчик обратных статусов от core.
6. Тесты: SKIP LOCKED, ровно одно `idea.ready` на `(id,rev)`, дубликат delivery в core не создаёт второй production (контрактный/e2e с fake core).

Код module-video в этом PR **не меняется** — только эта спека и схемы в `contracts/`.

## 9. Заведение идей на MVP (через БД)

```sql
INSERT INTO topics (code, title, description, default_tags, default_platforms)
VALUES ('postgres_internals', 'PostgreSQL internals', 'Deep dives into Postgres',
        ARRAY['postgresql','databases'], ARRAY['instagram']);

INSERT INTO ideas (topic_id, title, description, hook, language, priority, status, ready_at, author)
VALUES (
  (SELECT id FROM topics WHERE code = 'postgres_internals'),
  'CREATE DATABASE copies a template',
  'Show that CREATE DATABASE copies template1; three everyday surprises.',
  'CREATE DATABASE creates nothing. It copies.',
  'en', 10, 'ready', now(), 'db:owner'
);
```

Черновики: `status = 'draft'`, без `ready_at`. В очередь: `UPDATE … SET status = 'ready', ready_at = now(), rev = rev + 1`.

## 10. Открытые вопросы

1. Обратный канал статусов: событие AMQP vs `POST` module-video admin/internal — выбрать при реализации core consumer.
2. Нужен ли `queued` отдельно от `ready`/`dispatched`, или двух статусов достаточно (как в §4.3).
3. Согласовать D20 (админ-команды бота) с решением «бот только ревью»: идеи и темы на MVP только через БД — подтверждено для этого документа.
4. UUIDv5 namespace (фиксированный UUID проекта) — зашить в код module-video и core одинаково.
5. После переноса: миграция данных из core.`ideas` (если успеют появиться строки) → video.`ideas` одноразовым скриптом.
