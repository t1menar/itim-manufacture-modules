# mf-storage

Shared MinIO/S3 helpers for Manufacture **Python modules** (not core domain).

- Parse `s3://manufacture/<production_id>/<stage>/<attempt>/…`
- Presigned GET with separate **internal** vs **public** endpoints (SigV4 host)
- Used by `module-publish` (Instagram `video_url`) and `module-review` (Telegram `sendVideo` URL)

## Env

| Var | Meaning |
|-----|---------|
| `S3_ENDPOINT` | Internal S3 API host:port (`minio:9000`, `127.0.0.1:59000`) |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Keys (env/vault only) |
| `S3_BUCKET` | Default `manufacture` |
| `S3_SECURE` | `1` if internal TLS |
| `S3_PUBLIC_ENDPOINT` | Public host for Instagram/Telegram (TLS reverse proxy) |
| `S3_PUBLIC_SECURE` | Default `1` when public endpoint set |

## Local

```bash
./deploy/scripts/mfinfra-minio.sh
export S3_ENDPOINT=127.0.0.1:59000 S3_ACCESS_KEY=manufacture S3_SECRET_KEY=manufacture_dev_secret
export S3_BUCKET=manufacture S3_SECURE=0 S3_PUBLIC_ENDPOINT=127.0.0.1:59000 S3_PUBLIC_SECURE=0
cd packages/mf-storage && uv sync && uv run pytest
```
