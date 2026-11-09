# mf-storage

Shared MinIO/S3 helpers for Manufacture **Python modules** (not core domain).

- Parse `s3://manufacture/<production_id>/<stage>/<attempt>/…`
- Presigned GET with separate **internal** vs **public** endpoints (SigV4 host)
- Used by `module-publish` (Instagram `video_url`) and `module-review` (Telegram `sendVideo` URL)

## Local default

```bash
# from repo root
docker compose -f deploy/compose.minio.yml up -d
# or: ./deploy/scripts/mfinfra-minio.sh

export S3_ENDPOINT=127.0.0.1:59000
export S3_ACCESS_KEY=manufacture
export S3_SECRET_KEY=manufacture_dev_secret
export S3_BUCKET=manufacture
export S3_SECURE=0
# Same host for local; Instagram Graph needs a *publicly reachable* URL —
# temporarily tunnel port 59000 (cloudflared/ngrok) and set:
#   S3_PUBLIC_ENDPOINT=<tunnel-host>  S3_PUBLIC_SECURE=1
export S3_PUBLIC_ENDPOINT=127.0.0.1:59000
export S3_PUBLIC_SECURE=0

cd packages/mf-storage && uv sync && uv run pytest
```

No permanent domain or TLS reverse-proxy is required for local/dev.

## Env

| Var | Meaning |
|-----|---------|
| `S3_ENDPOINT` | Internal S3 API host:port (`127.0.0.1:59000`, `minio:9000`) |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Keys (module DB preferred; env = local fallback) |
| `S3_BUCKET` | Default `manufacture` |
| `S3_SECURE` | `1` if internal uses HTTPS |
| `S3_PUBLIC_ENDPOINT` | Host embedded in presigned URLs (tunnel host for live IG) |
| `S3_PUBLIC_SECURE` | `1` when public endpoint is HTTPS (typical for tunnels) |
