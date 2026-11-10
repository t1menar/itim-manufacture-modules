#!/bin/sh
set -eu
USER="${MINIO_ROOT_USER:-manufacture}"
PASS="${MINIO_ROOT_PASSWORD:-manufacture_dev_secret}"
BUCKET="${S3_BUCKET:-manufacture}"
/usr/local/bin/minio server /data --address ":9000" --console-address ":9001" &
pid=$!
i=0
while [ "$i" -lt 60 ]; do
  if curl -sf http://127.0.0.1:9000/minio/health/live >/dev/null; then
    break
  fi
  i=$((i + 1))
  sleep 0.5
done
mc alias set local http://127.0.0.1:9000 "$USER" "$PASS" >/dev/null
mc mb --ignore-existing "local/${BUCKET}" >/dev/null || true
wait "$pid"
