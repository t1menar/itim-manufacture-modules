# Локальный MinIO для модулей

Полный стек (PostgreSQL, RabbitMQ, старое ядро, admin-api и модули) больше не входит в этот репозиторий. Он сохранён в теге [`v1-legacy`](https://github.com/t1menar/itim-manufacture-modules/tree/v1-legacy). Новое ядро собирается в [manufacture-core](https://github.com/t1menar/manufacture-core).

Здесь остался только отдельный MinIO: его используют module-review и module-publish для локальных проверок и presigned URL.

```bash
# нужен Docker + Compose v2
docker compose -f deploy/compose.minio.yml up -d
# или:
./deploy/scripts/mfinfra-minio.sh
```

По умолчанию API слушает `127.0.0.1:59000`, консоль — `59001`. Учётные данные и бакет задаются переменными `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` и `S3_BUCKET` (см. `.env.example`). Образ собирается из `Dockerfile.minio` (официальные образы с Docker Hub / Quay часто недоступны).

Для живого Instagram туннелируйте порт 59000 (cloudflared/ngrok) и пропишите host туннеля в `S3_PUBLIC_ENDPOINT` / `module_settings.s3.public_endpoint`, `S3_PUBLIC_SECURE=1`.
