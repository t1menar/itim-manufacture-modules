# Локальный стек Manufacture

Один вход: **`./deploy/up.sh`** — поднимает PostgreSQL, RabbitMQ, MinIO, core (Go) и модули video / review / publish, регистрирует их в core и проверяет health.

## Быстрый старт

```bash
# нужен Docker + Compose v2
./deploy/up.sh              # анимированные логи
./deploy/up.sh --verbose    # поток stdout команд
./deploy/status.sh
./deploy/logs.sh core       # или без аргумента — все
./deploy/down.sh            # остановить (тома сохраняются)
```

При первом запуске создаётся `deploy/.env` с локальными паролями и `CORE_ADMIN_TOKEN` (`mfa_…`). Файл в `.gitignore` — **не коммитьте**. Секреты в лог не печатаются.

Повторный `up.sh` идемпотентен: реестр модулей, тома и `.env` переиспользуются.

## Video: реальная генерация

`up.sh` собирает module-video из `module-video/Dockerfile` (ffmpeg, prompts, reference), запускает его с `MVIDEO_PIPELINE=real` и снятой паузой идей. Дальше один раз:

```bash
./deploy/scripts/video-prepare.sh      # registry :5000, образ агента по digest, digest postgres:17, настройки video-claude в core
./deploy/scripts/video-credential.sh   # токен Claude -> таблица credentials (ввод скрыт); REF по умолчанию CLAUDE_OAUTH_TOKEN
./deploy/scripts/video-idea.sh "Title" "Description" "Hook line"   # идея -> очередь шедулера
```

Шедулер module-video отдаёт `idea.ready` в core, core создаёт задание, готовый ролик попадает в MinIO (бакет `manufacture`). Образ агента `video-agent:dev` собирается из `module-video/agent/Dockerfile`, если его нет.

## Реальные Telegram и Instagram

Переключение на real делается в базах модулей (DB приоритетнее env), перезапуск не нужен:

```bash
./deploy/scripts/review-telegram.sh     # токен бота (скрытый ввод); admin/chat ids необязательны
./deploy/scripts/review-master-token.sh # мастер-пароль: его админ отправляет боту в личку, чтобы зарегистрироваться
./deploy/scripts/publish-instagram.sh   # INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID -> аккаунт itim
```

`--dry-run` печатает SQL с замаскированными секретами. Туннель и публичный адрес MinIO не нужны: файл ролика читается из локального MinIO и загружается напрямую в Telegram (multipart, до 50 МБ; больше — ссылка) и в Instagram (resumable upload через `rupload.facebook.com`). Режим по ссылке остаётся запасным: `PUBLISH_INSTAGRAM_UPLOAD_MODE=url`. Готовые ролики всегда остаются в MinIO (бакет `manufacture`) как история.

### Окружения песочницы

`video-prepare.sh` описывает окружения, в которых video показывает команды: `postgres17` и, если образ есть локально, `kafka44` (официальный `apache/kafka:4.4.0`, один узел KRaft, без сети; `docker pull apache/kafka:4.4.0`, затем повторить `video-prepare.sh`). Идеи берутся только под эти окружения; темы-плейлисты задаются полем `topics.code` в базе `video` (`postgres_internals`, `kafka_internals`).

## Порты (по умолчанию)

| Сервис | URL |
|--------|-----|
| core | http://127.0.0.1:58080 |
| module-video | http://127.0.0.1:58081 |
| module-review | http://127.0.0.1:58082 |
| module-publish | http://127.0.0.1:58083 |
| admin-api (localhost only) | http://127.0.0.1:58084 |
| PostgreSQL | 127.0.0.1:56432 |
| RabbitMQ AMQP / UI | 56672 / 56673 |
| MinIO S3 / console | 56000 / 56001 |

Отдельный MinIO без полного стека: `docker compose -f deploy/compose.minio.yml up -d` или `./deploy/scripts/mfinfra-minio.sh`.

## Регистрация модулей

`up.sh` вызывает admin API core:

1. `deploy/scripts/register-modules.py` читает `GET {module}/info`, оставляет поля `modules.Info` (без `input_schema`/`output_schema`) и шлёт `POST /internal/v1/modules` с `manifest` + `Authorization: Bearer $CORE_ADMIN_TOKEN`.
2. При первой регистрации (или если в `.env` ещё `mft_pending_*`) в `.env` пишутся `MODULE_TOKEN_*` (`mft_…`), модули пересоздаются.
3. `POST /internal/v1/modules/self/heartbeat` от имени модуля → `health=up`.
4. `POST /internal/v1/modules/{id}/activate` `{replace:true}` → **active** для стадии.

Идентификаторы: `video-claude`, `review-telegram`, `publish-instagram`. Стадии/пайплайн/канал `itim` уже в seed-миграциях core (`0002_seed.sql`).

## Креды (Telegram / Instagram / MinIO keys)

По умолчанию **fake**-режимы (`REVIEW_TELEGRAM_MODE=fake`, `PUBLISH_INSTAGRAM_MODE=fake`) — реальных отправок нет.

Для real-режимов вставьте секреты в БД модулей (SQL-шаблоны в README `module-review` / `module-publish`): `module_secrets`, `platform_accounts.access_token`. Шифрование для local не требуется.

## Instagram + MinIO

Graph API должен скачать видео по **публичному** HTTPS URL. Локально:

```bash
cloudflared tunnel --url http://127.0.0.1:56000
# или ngrok http 56000
```

Пропишите host туннеля в `S3_PUBLIC_ENDPOINT` / `module_settings.s3.public_endpoint` и `S3_PUBLIC_SECURE=1`. Постоянный домен/TLS не обязательны.

## Структура

```
deploy/
  up.sh down.sh status.sh logs.sh
  compose.yml           # полный стек
  compose.minio.yml     # только MinIO (совместим по портам)
  Dockerfile.core
  lib/log.sh            # спиннеры, шаги [n/N], цвета, лог-файл
  scripts/register-modules.sh
  scripts/mfinfra-minio.sh
  postgres/01-create-dbs.sql
  .env.example
```

Анимация/цвета отключаются без TTY, при `NO_COLOR=1` или `CI=1`. Полный лог прогона: `deploy/.logs/<timestamp>.log`.

## Замечания по окружению

- Сеть compose: статические IP `172.28.0.0/16` + `extra_hosts` — стек поднимается даже если embedded DNS Docker (`127.0.0.11`) недоступен.
- Если контейнеры не видят друг друга по TCP при `dockerd --iptables=false`: `sudo sysctl -w net.bridge.bridge-nf-call-iptables=0 net.bridge.bridge-nf-call-ip6tables=0`.
- Официальный MinIO с Docker Hub часто недоступен → локальный образ `deploy/Dockerfile.minio`.


## admin-api (D24)

Панель ещё не в этом PR. Шлюз: `http://127.0.0.1:58084` (порт опубликован только на loopback). Входа нет. Примеры:

```bash
curl -sS http://127.0.0.1:58084/health
curl -sS http://127.0.0.1:58084/api/v1/overview
curl -sS http://127.0.0.1:58084/api/v1/modules
```

Секреты модулей: `PUT /api/v1/{video,review,publish}/...` — запись значения разрешена, чтение только маска/наличие.
