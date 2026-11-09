#!/usr/bin/env bash
# Start (or reuse) MinIO under /tmp/mfinfra for local module tests.
# Prefers docker compose; falls back to MinIO server binary in /tmp/mfinfra/bin.
set -euo pipefail
ROOT="${MFINFRA_ROOT:-/tmp/mfinfra}"
PORT="${S3_PORT:-59000}"
CONSOLE_PORT="${S3_CONSOLE_PORT:-59001}"
USER="${MINIO_ROOT_USER:-manufacture}"
PASS="${MINIO_ROOT_PASSWORD:-manufacture_dev_secret}"
COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/compose.minio.yml"
mkdir -p "$ROOT/minio/data" "$ROOT/bin"

start_via_docker() {
  command -v docker >/dev/null 2>&1 || return 1
  export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-mfinfra}"
  cd "$(dirname "$COMPOSE_FILE")"
  docker compose -f "$COMPOSE_FILE" up -d
  return 0
}

start_via_binary() {
  local bin="$ROOT/bin/minio"
  if [ ! -x "$bin" ]; then
    echo "MinIO binary missing at $bin — download from GitHub releases (linux-amd64)." >&2
    return 1
  fi
  if curl -sf "http://127.0.0.1:${PORT}/minio/health/live" >/dev/null 2>&1; then
    return 0
  fi
  export MINIO_ROOT_USER="$USER" MINIO_ROOT_PASSWORD="$PASS"
  nohup "$bin" server "$ROOT/minio/data" --address ":${PORT}" --console-address ":${CONSOLE_PORT}" \
    >"$ROOT/minio/minio.log" 2>&1 &
  echo $! >"$ROOT/minio/minio.pid"
  for _ in $(seq 1 40); do
    curl -sf "http://127.0.0.1:${PORT}/minio/health/live" >/dev/null && break
    sleep 0.25
  done
}

if ! curl -sf "http://127.0.0.1:${PORT}/minio/health/live" >/dev/null 2>&1; then
  start_via_docker || start_via_binary
fi

if [ -x "$ROOT/bin/mc" ]; then
  "$ROOT/bin/mc" alias set local "http://127.0.0.1:${PORT}" "$USER" "$PASS" >/dev/null
  "$ROOT/bin/mc" mb --ignore-existing "local/manufacture" >/dev/null || true
fi

echo "S3_ENDPOINT=127.0.0.1:${PORT}"
echo "S3_ACCESS_KEY=${USER}"
echo "S3_SECRET_KEY=${PASS}"
echo "S3_BUCKET=manufacture"
echo "S3_SECURE=0"
echo "S3_PUBLIC_ENDPOINT=127.0.0.1:${PORT}"
echo "S3_PUBLIC_SECURE=0"
