#!/usr/bin/env bash
set -Eeuo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_ROOT"
COMPOSE=(docker compose -f compose.yml)
[[ -f .env ]] && COMPOSE+=(--env-file .env)
svc="${1:-}"
if [[ -n "$svc" ]]; then
  exec "${COMPOSE[@]}" logs -f --tail=200 "$svc"
fi
exec "${COMPOSE[@]}" logs -f --tail=100
