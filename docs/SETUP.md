# Поднять стек iTim + Manufacture на новой машине

Секретов в этом файле нет. Все значения (ключи, токены) берутся из `deploy/.env`, который в git не попадает.

## Репозитории (клонировать рядом, по SSH)

| Репозиторий | Ветка | Зачем |
|---|---|---|
| [t1menar/itim-manufacture-modules](https://github.com/t1menar/itim-manufacture-modules) | `main` | модули iTim, `deploy/compose.yml`, пайплайн `docs/pipeline.example.yaml` |
| [t1menar/manufacture-core](https://github.com/t1menar/manufacture-core) | `c6/docker-compose` | ядро; в этой ветке Dockerfile (с админкой) и compose |
| [t1menar/manufacture-sdk-python](https://github.com/t1menar/manufacture-sdk-python) | `main` | SDK (контракт 0.3.0); образы модулей ставят его с GitHub по закреплённому коммиту |

```bash
mkdir -p ~/projects && cd ~/projects
git clone git@github.com:t1menar/itim-manufacture-modules.git
git clone -b c6/docker-compose git@github.com:t1menar/manufacture-core.git
git clone git@github.com:t1menar/manufacture-sdk-python.git   # нужен только для разработки
```

Структура важна: `deploy/compose.yml` собирает ядро из `../../manufacture-core`.

## Что нужно на машине
Docker (с compose), git, доступ по SSH к GitHub. Python и Go локально не нужны (всё собирается в Docker).

## Конфигурация
```bash
cd itim-manufacture-modules/deploy
cp .env.example .env     # заполнить все значения, поля описаны в файле
```
Ключевое:
- `MF_ADMIN_TOKEN` не короче 32 символов (иначе ядро не стартует);
- MinIO: сейчас `ziphy.ru:9000` (https), ключи и бакеты `manufacture`, `mf-blobs`;
- Anthropic: либо `ANTHROPIC_API_KEY` (`sk-ant-api…`), либо `CLAUDE_CODE_OAUTH_TOKEN` (`sk-ant-oat…`, подписка);
- Telegram: `MTGR_BOT_TOKEN`, `MTGR_OWNERS`; Instagram: `MIPUB_TOKEN_MAIN`;
- `MIDEA_MIN_INTERVAL_S`: для тестов 0, для работы 3600.

## Запуск
```bash
docker compose --env-file .env up -d --build
# применить пайплайн (модули + pipeline video)
docker compose cp ../docs/pipeline.example.yaml core:/tmp/p.yaml
docker compose --env-file .env exec -T core /usr/local/bin/mfctl apply -f /tmp/p.yaml
# вариант без публикации в Instagram (для тестов):
#   docs/pipeline.test-no-publish.yaml
```
- Админка ядра: http://127.0.0.1:8080, вход по `MF_ADMIN_TOKEN`.
- Состояние: `docker compose --env-file .env exec -T core /usr/local/bin/mfctl get modules` и `... get runs`.
- Запуск по источнику идей: `... mfctl run video`.
- Идеи пока создаются вручную через сервис модуля `idea` (см. `modules/module-idea`), отдельного UI нет.

## Документация
- Архитектура и модули: [AGENTS.md](../AGENTS.md), [docs/PIPELINE.md](PIPELINE.md)
- Требования к платформе: [docs/PLATFORM_REQUIREMENTS.md](PLATFORM_REQUIREMENTS.md)
- Контракт ядра 0.3.0: [manufacture-core/docs/messaging.md](https://github.com/t1menar/manufacture-core/blob/main/docs/messaging.md), паттерн гейта ревью: [docs/patterns/review-gate.md](https://github.com/t1menar/manufacture-core/blob/main/docs/patterns/review-gate.md)

## Хранилище MinIO на сервере (ziphy.ru)
Собран из исходников (`github.com/minio/minio`, бинарники сняты с раздачи), работает как systemd-сервис `minio` за Caddy на `https://ziphy.ru:9000`. Данные: `/var/lib/minio/data`, ключи: `/etc/minio.env` на сервере.

## Состояние работ и что осталось
- Проверено: ядро, брокер, 5 модулей, источник идей, шаг `scenario` до агента, уведомления о запуске, сбои → `needs_attention`.
- Не готово: эндпоинт `confirm` и токены модулей в ядре (нужны для публикации в Instagram); передача расхода при сбое сценария;
  тестовая идея на 1 секунду не проходит формат `manufacture.scenario/1` (требует песочницу и ≥15 с) — нужна идея с реальной демонстрацией либо расширение формата;
  запись аккаунта `main` в таблицу `accounts` модуля `instagram-publisher`.
- Безопасность: сменить пароль root сервера (был в чате); для продакшена вернуть `MIDEA_MIN_INTERVAL_S=3600`.
