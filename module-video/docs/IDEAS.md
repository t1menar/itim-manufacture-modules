# Идеи и темы в module-video (D21)

_Статус: спецификация. Реализацию шедулера и изменения core этот документ не делает._  
_Дата: 2026-11-09 (Europe/Stockholm)._  
_Решения по открытым вопросам (владелец): обратные статусы — RabbitMQ; статус `queued` — да; core без доменных частей модулей (идеи полностью вне core)._

## 1. Решение

Все идеи роликов и справочник тем живут **только** в БД `video` (module-video).

Core:

- **не** имеет таблицы `ideas` и **не** мигрирует в неё данные;
- хранит на production только непрозрачный `idea_ref` (`id` + `rev`);
- оркестрирует pipeline (jobs, fencing, outbox/inbox), не интерпретирует поля идеи.

Поток MVP:

1. Админ заводит тему и идею **в БД video** (бот только для ревью).
2. Идея проходит `draft → ready → queued`; шедулер **module-video** публикует `idea.ready` через transactional outbox.
3. Core потребляет `idea.ready` (inbox dedup), создаёт production с `idea_ref`, шлёт job модулю video.
4. Модуль video **сам читает идею по `idea_ref`** из своей БД (см. §6.4).
5. Core шлёт обратные статусы идеи в RabbitMQ (`idea.in_production` / `idea.done` / `idea.failed`); module-video применяет их через inbox dedup.

## 2. Что уже есть (на `origin/main`)

### 2.1 module-video

| Что | Где | Замечание |
|-----|-----|-----------|
| Вход job `input.idea {id, text, language}` | `contract.Idea`, `intake.py` | будет заменён на `idea_ref` (§6.4, §8) |
| «topic» в артефактах | analysis / post / metadata | не справочник тем |
| БД runs/steps/prompts | миграции `0001`–`0003` | таблиц `ideas`/`topics` **нет** |

### 2.2 core (убрать / заменить)

| Что | Действие |
|-----|----------|
| Таблица `ideas`, `Engine.Tick` | **удалить** (не депрекейт с переносом строк) |
| Job input с полями идеи | заменить на `idea_ref`; модуль читает сам |
| `productions.idea_id` FK | заменить на `idea_ref` text (+ разбор id/rev при необходимости только как оркестрационный ключ идемпотентности) |

## 3. Владение данными

| Сущность | Владелец | Core |
|----------|----------|------|
| `topics`, `ideas`, снимки/rev идеи, outbox шедулера, inbox статусов | БД `video` | нет |
| Production / jobs / variants / events / outbox jobs | БД `core` | только `idea_ref` на production |
| Pipeline, module registry, job fencing | core | оркестрация |

После `queued`→`dispatched` контент данной `rev` неизменяем в module-video.

## 4. Модель

### 4.1 Тема (`topics`)

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `id` | bigint identity PK | |
| `code` | text | unique, `^[a-z][a-z0-9_]{1,63}$` |
| `title` | text | 1…120 |
| `description` | text | null / ≤4000 |
| `default_tags` | text[] | без `#`, `^[a-z0-9_]{2,40}$`, ≤20 |
| `default_platforms` | text[] | напр. `{instagram}`, ≤8 |
| `active` | boolean | default true |
| `rev` | int | ≥1 |
| `created_at` / `updated_at` | timestamptz | |

Неактивную тему нельзя ставить в `ready`/`queued`.

### 4.2 Идея (`ideas`)

| Поле | Тип | Ограничения |
|------|-----|-------------|
| `id` | bigint identity PK | |
| `topic_id` | bigint FK → topics | обязателен |
| `title` | text | 1…200 |
| `description` | text | 1…4000 |
| `hook` | text | null / ≤300 |
| `audience` | text | null / ≤500 |
| `tags` | text[] | без `#`; пусто → `topics.default_tags` при чтении |
| `references` | jsonb | `{url, note?}[]`, ≤20 |
| `constraints` | jsonb | `{duration_s?, format?, notes?}` |
| `language` | text | MVP: `en` |
| `priority` | int | −100…100 |
| `notes` | text | null / ≤2000 |
| `author` | text | null / `tg:<id>` / `db:<user>` |
| `pipeline_id` | text | null → default pipeline **как оркестрационный hint** в `idea.ready` |
| `status` | text | §4.3 |
| `rev` | int | ≥1; +1 при смене контента; фиксируется при уходе в `queued` |
| `ready_at` / `queued_at` / `dispatched_at` | timestamptz | null |
| `last_message_id` | uuid | message_id последнего `idea.ready` |
| `failure` | jsonb | null / `{code, message?}` |
| `created_at` / `updated_at` | timestamptz | |

Индекс шедулера: `(priority DESC, queued_at, id) WHERE status = 'queued'`.

Контент правится только в `draft` / `ready`.  
`priority`/`notes` — также в `failed` / `cancelled`.

### 4.3 Статусы идеи

```
draft → ready → queued → dispatched → in_production → done
                ↓          ↓              ↓
             cancelled  cancelled       failed → ready (правка) → queued
ready → draft | cancelled
done | failed | cancelled → archived
```

| Статус | Смысл |
|--------|--------|
| `draft` | черновик |
| `ready` | контент готов, ещё не в очереди отправки |
| `queued` | в очереди шедулера module-video |
| `dispatched` | `idea.ready` в outbox; эту `rev` повторно не шлём |
| `in_production` | core принял (`idea.in_production`) |
| `done` / `failed` / `cancelled` / `archived` | финал / архив |

`ready` → `queued`: админ SQL / позже API (`queued_at = now()`, при необходимости `rev = rev + 1` если контент менялся с прошлой отправки).  
`queued` → `dispatched`: **только** в одной транзакции с INSERT outbox (§5).

## 5. Шедулер (module-video)

### 5.1 Почему здесь

Бэклог и статус — в БД video; смена статуса + outbox = одна транзакция; core не читает чужой домен.

### 5.2 Цикл

1. `ideas.scheduler.paused` → выход.
2. `pg_advisory_xact_lock(hashtext('video.ideas.scheduler'))`.
3. Лимиты: `max_dispatch_per_tick` (default 5), `max_in_flight` (считаем `dispatched`+`in_production`).
4. `SELECT … FROM ideas WHERE status = 'queued' AND topic.active ORDER BY priority DESC, queued_at, id LIMIT n FOR UPDATE SKIP LOCKED`.
5. Для каждой: `idea_ref = idea:<id>:v<rev>`; `message_id = UUIDv5(MANUFACTURE_NS, idea_ref)`; INSERT outbox `idea.ready`; `status = dispatched`, `dispatched_at`, `last_message_id`.
6. Relay → exchange `manufacture.events`, routing key `idea.ready`.

Тик: `ideas.scheduler.tick_s` (default 5) + опционально `NOTIFY video_ideas`.

### 5.3 Без повторной отправки

| Слой | Механизм |
|------|----------|
| Publisher | `queued`→`dispatched` только из `queued`; UNIQUE `message_id` / `(idea_id, rev)` в outbox |
| Стабильный id | `message_id = UUIDv5(NS, "idea:<id>:v<rev>")` |
| Core consumer | inbox `(consumer, message_id)` |
| Production | UNIQUE live production на `idea_ref` (или на пару id+rev) |

Повтор: `failed`/`cancelled` → (правка) `ready` → `queued` с **новым** `rev`.

## 6. Контракты

Схемы: `contracts/topic.json`, `contracts/idea.json` (документ в module-video), `contracts/events/idea.ready.json`, `contracts/events/idea.status.json`.

### 6.1 Документ идеи (внутри module-video; core не хранит)

См. `contracts/idea.json` — title, description, topic, tags, …

### 6.2 Событие `idea.ready` (module-video → core)

Envelope: `type=idea.ready`, `producer=module:video`, `message_id` = UUIDv5 от `idea_ref`.

Payload — **только оркестрационные поля**, без домена идеи:

```json
{
  "idea_ref": { "id": 42, "rev": 3 },
  "language": "en",
  "pipeline_id": null,
  "priority": 10
}
```

`language` / `pipeline_id` / `priority` — hints для routing и слотов concurrency в core, не контент ролика.

Core bind: `idea.#` на `manufacture.events`.

### 6.3 Обратные статусы (core → module-video) — RabbitMQ

Exchange: `manufacture.events` (или `manufacture.commands` с bind на очередь module-video).  
Routing keys: `idea.in_production`, `idea.done`, `idea.failed` (тип envelope совпадает).

| Когда в core | Событие | Эффект в module-video |
|--------------|---------|------------------------|
| production создан по `idea.ready` | `idea.in_production` | `dispatched`→`in_production` |
| production `done` | `idea.done` | →`done` |
| production `failed` / нет route/pipeline | `idea.failed` | →`failed` + `failure` |

Payload (`contracts/events/idea.status.json`):

```json
{
  "idea_ref": { "id": 42, "rev": 3 },
  "production_id": "018f…",
  "status": "in_production",
  "failure": null
}
```

`message_id = UUIDv5(NS, "idea:<id>:v<rev>:" + status + ":" + production_id)` — стабильный, at-least-once безопасен.  
module-video: inbox dedup по `message_id`; монотонность статусов (`dispatched` < `in_production` < `done|failed`); устаревшие события → outcome `stale`.

Очередь: `module.video.commands` (или отдельная `module.video.idea-status`) bind на `idea.in_production` / `idea.done` / `idea.failed`.

### 6.4 Job input: модуль читает идею по ref

**Выбор:** в job request core передаёт только

```json
"input": {
  "idea_ref": { "id": 42, "rev": 3 },
  "channels": [ … ],
  "upstream": {}
}
```

Module-video при intake загружает документ идеи `WHERE id=42 AND rev=3` (или из таблицы снимков, зафиксированной при `queued`→`dispatched`).

**Почему не opaque payload в core:**

1. Владелец сказал: в core не должно быть доменных частей модулей — снимок title/description/topic в core снова тащит домен.
2. Источник истины уже в video DB; модуль и так автор `idea.ready`.
3. Core остаётся оркестратором: значет `idea_ref`, language/pipeline hints, не парсит контент.
4. Провенанс контента идеи — в result/provenance модуля, не в core.

Совместимость: текущий `contract.Idea {id,text,language}` нужно сменить на загрузку по ref (работа владельца module-video, §8).

## 7. Что меняется в core (план, не в этом PR)

1. **Удалить** таблицу `ideas` и `Engine.Tick` / `startIdea` / `failIdea`. Данные не переносим.
2. Consumer `idea.ready` → создать production + variant + первый job; записать `productions.idea_ref` (text `idea:<id>:v<rev>` или jsonb `{id,rev}`).
3. Job input video: `idea_ref` вместо полей идеи.
4. При create/complete/fail production — outbox `idea.in_production` / `idea.done` / `idea.failed`.
5. Envelope enum + схемы событий; bind `idea.#`.
6. Уникальность: один live production на `idea_ref`.

## 8. Что добавить в module-video (владельцу)

1. Миграции: `topics`, `ideas`, outbox, `amqp_inbox` (статусы).
2. Шедулер + relay; consumer обратных статусов.
3. Снимок на `rev` при постановке в `queued`/`dispatched` (чтобы job по ref был детерминирован).
4. Intake: загрузка по `idea_ref` вместо `input.idea.text`.
5. MVP SQL seed (§9); HTTP admin — позже.
6. Тесты: одно `idea.ready` на `(id,rev)`; дубликат status-события идемпотентен; job без строки идеи → fail/blocked.

Код module-video в этом PR не меняется (кроме ссылки в README).

## 9. Заведение на MVP (БД)

```sql
INSERT INTO topics (code, title, description, default_tags, default_platforms)
VALUES ('postgres_internals', 'PostgreSQL internals', 'Deep dives into Postgres',
        ARRAY['postgresql','databases'], ARRAY['instagram']);

INSERT INTO ideas (topic_id, title, description, hook, language, priority, status, author)
VALUES (
  (SELECT id FROM topics WHERE code = 'postgres_internals'),
  'CREATE DATABASE copies a template',
  'Show that CREATE DATABASE copies template1; three everyday surprises.',
  'CREATE DATABASE creates nothing. It copies.',
  'en', 10, 'draft', 'db:owner'
);

-- контент готов:
UPDATE ideas SET status = 'ready', ready_at = now() WHERE id = …;

-- в очередь шедулера:
UPDATE ideas SET status = 'queued', queued_at = now() WHERE id = … AND status = 'ready';
```

## 10. Решённые вопросы (закрыты в D21)

| # | Вопрос | Решение владельца |
|---|--------|-------------------|
| 1 | Обратный канал статусов | **RabbitMQ** (`idea.in_production` / `done` / `failed`), inbox dedup в module-video |
| 2 | Отдельный статус `queued` | **Да** (`ready` ≠ `queued` ≠ `dispatched`) |
| 3 | Домен в core | Core только оркестрация; идеи **полностью** вне core, без таблицы и без миграции строк |
| — | Как job получает контент | Модуль **читает по `idea_ref`** (§6.4) |
| — | UUIDv5 namespace | Общая константа `MANUFACTURE_NS` в module-video и core (зашить при реализации) |

Открытых вопросов по этому документу нет.
