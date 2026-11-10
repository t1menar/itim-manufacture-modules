# deploy — context for agents

`./deploy/up.sh` brings up Postgres 17, RabbitMQ 4, MinIO (locally built `Dockerfile.minio`), core, video, review, publish, admin-api(+panel); creates `deploy/.env` once (gitignored, holds
passwords, `CORE_ADMIN_TOKEN`, module tokens, Instagram video host key — **never print it**), registers and activates modules (`scripts/register-modules.py`), smoke-checks health.
Other scripts: `status.sh`, `logs.sh`, `down.sh` (volumes kept), `scripts/video-prepare.sh` (registry :5000, agent image by digest, sandbox env digests, `video-claude` settings in core),
`video-credential.sh`, `video-idea.sh "Title" "Desc" "Hook"`, `review-telegram.sh`, `review-master-token.sh`, `review-admin-reset.sh`, `publish-instagram.sh` (`--dry-run` masks secrets), `mfinfra-minio.sh`.
Compose service images default to `manufacture-<svc>:local` (override with `*_IMAGE`). Volumes: `manufacture_pg_data`, `manufacture_minio_data`; agent workspaces `video-ws-*`, `video-src-*`.
Full cleanup: `docker compose -f deploy/compose.yml --env-file deploy/.env down -v --rmi all` plus leftover `video-agent*` containers/volumes. Compose uses static IPs `172.28.0.0/16` + `extra_hosts`.
Instagram-related env: `PUBLISH_INSTAGRAM_*`, `PUBLISH_VIDEO_HOST*` (see `.env.example`). Telegram/Instagram default to `real` in Compose; set `…_MODE=fake` for local runs without sends.
