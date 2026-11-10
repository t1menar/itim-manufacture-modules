# deploy — context for agents

This directory only ships a standalone MinIO used by module-review and module-publish for local tests and presigned URLs. Start it with `docker compose -f deploy/compose.minio.yml up -d` or `./deploy/scripts/mfinfra-minio.sh` (Compose, then a local binary under `/tmp/mfinfra`). Default ports: API 59000, console 59001. Image is built from `Dockerfile.minio` because official Hub/Quay MinIO images are often blocked.

The previous full local stack (`up.sh`, Postgres, RabbitMQ, core, admin-api, module registration, video/review/publish helper scripts) lived here and is preserved on tag `v1-legacy`. The new core is https://github.com/t1menar/manufacture-core.

Never print `deploy/.env` or MinIO passwords.
