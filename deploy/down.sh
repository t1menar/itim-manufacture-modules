#!/usr/bin/env bash
set -Eeuo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/log.sh
source "${DEPLOY_ROOT}/lib/log.sh"
mf_log_init 1
mf_banner "Manufacture · down"
cd "$DEPLOY_ROOT"
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi
COMPOSE=(docker compose -f "${DEPLOY_ROOT}/compose.yml")
[[ -f .env ]] && COMPOSE+=(--env-file "${DEPLOY_ROOT}/.env")
mf_step_begin "docker compose down"
mf_run "${COMPOSE[@]}" down --remove-orphans
mf_step_end ok "контейнеры остановлены"
mf_info "тома сохранены (данные БД/MinIO). Полная очистка: docker compose down -v"
mf_summary_footer
