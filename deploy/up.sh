#!/usr/bin/env bash
# Manufacture local stack bring-up with animated logs.
set -Eeuo pipefail

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/log.sh

# /etc/hosts fallback when Docker embedded DNS (127.0.0.11) is down
ADD_HOSTS=(
  --add-host=postgres:172.28.0.10
  --add-host=rabbitmq:172.28.0.11
  --add-host=minio:172.28.0.12
  --add-host=core:172.28.0.20
  --add-host=module-video:172.28.0.21
  --add-host=module-review:172.28.0.22
  --add-host=module-publish:172.28.0.23
)
source "${DEPLOY_ROOT}/lib/log.sh"

VERBOSE=0
SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    -v|--verbose) VERBOSE=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      cat <<HINT
Usage: ./deploy/up.sh [--verbose] [--skip-build]

Поднимает PostgreSQL, RabbitMQ, MinIO, core, module-video/review/publish,
регистрирует модули в core и делает smoke-check.

Лог: deploy/.logs/<timestamp>.log
HINT
      exit 0
      ;;
    *)
      echo "unknown flag: $arg" >&2
      exit 2
      ;;
  esac
done

export PATH="${PATH}:/usr/local/bin"
mf_log_init 12
[[ "$VERBOSE" == "1" ]] && mf_log_set_verbose
mf_banner "Manufacture · локальный стек"

cd "$DEPLOY_ROOT"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-manufacture}"
COMPOSE=(docker compose -f "${DEPLOY_ROOT}/compose.yml" --env-file "${DEPLOY_ROOT}/.env")


wait_container_healthy() {
  local name="$1"
  local timeout="${2:-90}"
  local i
  for i in $(seq 1 "$timeout"); do
    local st
    st=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || echo missing)
    if [[ "$st" == "healthy" || "$st" == "running" ]]; then
      # Prefer explicit healthy when healthcheck exists
      if docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null | grep -q healthy; then
        return 0
      fi
      if ! docker inspect --format '{{if .State.Health}}yes{{end}}' "$name" 2>/dev/null | grep -q yes; then
        [[ "$st" == "running" ]] && return 0
      fi
    fi
    sleep 1
  done
  return 1
}

# HTTP check from inside the compose network (works even when host port publish is broken).
curl_net() {
  local url="$1"
  docker run --rm --network manufacture "${ADD_HOSTS[@]}" curlimages/curl:8.5.0 \
    -sf --max-time 5 "$url" >/dev/null 2>&1
}

wait_http_net() {
  local url="$1"
  local timeout="${2:-90}"
  local i
  for i in $(seq 1 "$timeout"); do
    if curl_net "$url"; then
      return 0
    fi
    # Fallback: host loopback (normal Docker Desktop / Linux with iptables)
    if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}


# ---------- 1. deps ----------
mf_step_begin "Проверка docker / compose / curl / python3"
mf_run bash -c 'command -v docker >/dev/null'
mf_run bash -c 'docker info >/dev/null'
mf_run bash -c 'docker compose version >/dev/null'
mf_run bash -c 'command -v curl >/dev/null'
mf_run bash -c 'command -v python3 >/dev/null'
mf_step_end ok "зависимости на месте"

# ---------- 2. .env ----------
mf_step_begin "Файл .env (секреты локально, не печатаем)"
if [[ ! -f "${DEPLOY_ROOT}/.env" ]]; then
  cp "${DEPLOY_ROOT}/.env.example" "${DEPLOY_ROOT}/.env"
  # Generate secrets
  PG_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
  MINIO_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
  ADMIN=$(python3 -c 'import secrets; print("mfa_"+secrets.token_urlsafe(24))')
  MASTER=$(python3 -c 'import base64,os; print("1:"+base64.b64encode(os.urandom(32)).decode())')
  # portable in-place replace
  python3 - "$DEPLOY_ROOT/.env" "$PG_PASS" "$MINIO_PASS" "$ADMIN" "$MASTER" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
pg, mn, adm, master = sys.argv[2:6]
text = path.read_text()
repl = {
    "POSTGRES_PASSWORD=change_me": f"POSTGRES_PASSWORD={pg}",
    "MINIO_ROOT_PASSWORD=change_me": f"MINIO_ROOT_PASSWORD={mn}",
    "CORE_ADMIN_TOKEN=": f"CORE_ADMIN_TOKEN={adm}",
    "CORE_MASTER_KEY=": f"CORE_MASTER_KEY={master}",
}
for k, v in repl.items():
    if k in text:
        text = text.replace(k, v, 1)
path.write_text(text)
PY
  mf_info "создан deploy/.env (пароли/токены сгенерированы)"
else
  mf_info "используем существующий deploy/.env"
fi
# shellcheck disable=SC1091
set -a
source "${DEPLOY_ROOT}/.env"
set +a
mf_step_end ok ".env готов"

# ---------- 3. agent network ----------
mf_step_begin "Docker-сеть для video-агентов (${VIDEO_AGENT_NETWORK:-manufacture_agents})"
NET="${VIDEO_AGENT_NETWORK:-manufacture_agents}"
if docker network inspect "$NET" >/dev/null 2>&1; then
  mf_step_end skip "сеть уже есть"
else
  mf_run docker network create "$NET"
  mf_step_end ok "сеть создана"
fi

# ---------- 4. build ----------
mf_step_begin "Сборка образов (core / modules)"
if [[ "$SKIP_BUILD" == "1" ]]; then
  mf_step_end skip " --skip-build"
else
  mf_run "${COMPOSE[@]}" build
  mf_step_end ok "образы собраны"
fi

# ---------- 5. infra ----------
# На части окружений bridge-nf гоняет L2 через iptables без правил Docker → TCP между контейнерами мёртв.
if [[ "$(sysctl -n net.bridge.bridge-nf-call-iptables 2>/dev/null || echo 0)" == "1" ]]; then
  if sysctl -w net.bridge.bridge-nf-call-iptables=0 >/dev/null 2>&1 \
    && sysctl -w net.bridge.bridge-nf-call-ip6tables=0 >/dev/null 2>&1; then
    mf_info "отключён bridge-nf-call-iptables (иначе нет TCP между контейнерами)"
  else
    mf_warn "net.bridge.bridge-nf-call-iptables=1 — при проблемах с сетью: sudo sysctl -w net.bridge.bridge-nf-call-iptables=0"
  fi
fi

mf_step_begin "Старт PostgreSQL · RabbitMQ · MinIO"
mf_run "${COMPOSE[@]}" up -d postgres rabbitmq minio
for _wait in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-manufacture}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-manufacture}" >/dev/null 2>&1; then
  mf_step_end fail "postgres not ready"
  exit 1
fi
mf_step_end ok "инфра up"

# ---------- 6. wait infra health ----------
mf_step_begin "Ожидание healthcheck инфра-сервисов"
wait_container_healthy manufacture-postgres-1 60 || { mf_step_end fail "postgres"; exit 1; }
wait_container_healthy manufacture-rabbitmq-1 90 || { mf_step_end fail "rabbitmq"; exit 1; }
wait_container_healthy manufacture-minio-1 90 || { mf_step_end fail "minio"; exit 1; }
mf_step_end ok "postgres · rabbitmq · minio healthy"

# ---------- 7. core ----------
mf_step_begin "Старт core (миграции при serve)"
mf_run "${COMPOSE[@]}" up -d core
if ! wait_http_net "http://core:8080/health" 90; then
  mf_step_end fail "core /health timeout"
  "${COMPOSE[@]}" logs --no-color --tail=80 core >>"$MF_LOG_FILE" || true
  exit 1
fi
mf_step_end ok "core слушает :${CORE_PORT:-58080}"

# ---------- 8. modules ----------
mf_step_begin "Старт module-video · review · publish"
mf_run "${COMPOSE[@]}" up -d module-video module-review module-publish
for svc in module-video module-review module-publish; do
  if ! wait_http_net "http://${svc}:8080/health" 120; then
    mf_step_end fail "$svc /health timeout"
    "${COMPOSE[@]}" logs --no-color --tail=80 "$svc" >>"$MF_LOG_FILE" || true
    exit 1
  fi
done
mf_step_end ok "модули healthy"

# ---------- 9. register ----------
mf_step_begin "Регистрация модулей в core (POST /internal/v1/modules)"
export CORE_ADMIN_TOKEN
TOKENS_BEFORE=$(grep -E '^MODULE_TOKEN_' "${DEPLOY_ROOT}/.env" || true)
# Run registrar on the compose network (host→published ports may be unavailable).
if ! mf_run docker run --rm --network manufacture "${ADD_HOSTS[@]}" \
  -e CORE_URL=http://core:8080 \
  -e CORE_ADMIN_TOKEN \
  -e TOKENS_FILE=/tokens/.env \
  -v "${DEPLOY_ROOT}/.env:/tokens/.env" \
  -v "${DEPLOY_ROOT}/scripts/register-modules.py:/register.py:ro" \
  python:3.12-slim python /register.py; then
  mf_step_end fail "регистрация"
  exit 1
fi
TOKENS_AFTER=$(grep -E '^MODULE_TOKEN_' "${DEPLOY_ROOT}/.env" || true)
NEED_RESTART=0
if [[ "$TOKENS_BEFORE" != "$TOKENS_AFTER" ]]; then
  NEED_RESTART=1
fi
mf_step_end ok "модули в реестре"

# ---------- 10. restart with tokens ----------
mf_step_begin "Перезапуск модулей с выданными mft_ токенами"
if [[ "$NEED_RESTART" == "1" ]]; then
  # re-source .env after token write
  set -a
  # shellcheck disable=SC1091
  source "${DEPLOY_ROOT}/.env"
  set +a
  mf_run "${COMPOSE[@]}" up -d --force-recreate module-video module-review module-publish
  for svc in module-video module-review module-publish; do
    wait_http_net "http://${svc}:8080/health" 120 || {
      mf_step_end fail "$svc не поднялся после recreate"
      exit 1
    }
  done
  mf_step_end ok "токены применены"
else
  mf_step_end skip "токены уже были (идемпотентный повтор)"
fi

# ---------- 11. heartbeat + activate ----------
mf_step_begin "Heartbeat + activate (health=up → active)"
set -a
# shellcheck disable=SC1091
source "${DEPLOY_ROOT}/.env"
set +a
net_curl() {
  docker run --rm --network manufacture "${ADD_HOSTS[@]}" curlimages/curl:8.5.0 "$@" >/dev/null
}
hb() {
  local tok="$1"
  net_curl -sf -X POST "http://core:8080/internal/v1/modules/self/heartbeat" \
    -H "Authorization: Bearer ${tok}"
}
act() {
  local id="$1"
  net_curl -sf -X POST "http://core:8080/internal/v1/modules/${id}/activate" \
    -H "Authorization: Bearer ${CORE_ADMIN_TOKEN}" \
    -H "X-Admin-Actor: deploy:local" \
    -H "Content-Type: application/json" \
    -d '{"replace":true}'
}
mf_run hb "$MODULE_TOKEN_VIDEO"
mf_run hb "$MODULE_TOKEN_REVIEW"
mf_run hb "$MODULE_TOKEN_PUBLISH"
mf_run act video-claude
mf_run act review-telegram
mf_run act publish-instagram
mf_step_end ok "модули active"

# ---------- 12. smoke ----------
mf_step_begin "Smoke-check: /health + /info + active в core"
SMOKE_OK=1
for url in \
  "http://core:8080/health" \
  "http://module-video:8080/health" \
  "http://module-review:8080/health" \
  "http://module-publish:8080/health" \
  "http://module-video:8080/info" \
  "http://module-review:8080/info" \
  "http://module-publish:8080/info"
do
  if ! curl_net "$url"; then
    mf_warn "недоступно: $url"
    SMOKE_OK=0
  fi
done
# Verify active via settings get (admin) — if 200, module exists
for id in video-claude review-telegram publish-instagram; do
  code=$(docker run --rm --network manufacture "${ADD_HOSTS[@]}" curlimages/curl:8.5.0 -sS -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${CORE_ADMIN_TOKEN}" \
    -H "X-Admin-Actor: deploy:local" \
    "http://core:8080/internal/v1/modules/${id}/settings" || echo 000)
  if [[ "$code" != "200" ]]; then
    mf_warn "module $id settings HTTP $code"
    SMOKE_OK=0
  fi
done
if [[ "$SMOKE_OK" != "1" ]]; then
  mf_step_end fail "smoke"
  exit 1
fi
mf_step_end ok "smoke зелёный"

printf '\n'
mf_ok "Адреса (localhost)"
mf_table \
  "сервис|URL" \
  "core|http://127.0.0.1:${CORE_PORT:-58080}" \
  "module-video|http://127.0.0.1:${VIDEO_PORT:-58081}" \
  "module-review|http://127.0.0.1:${REVIEW_PORT:-58082}" \
  "module-publish|http://127.0.0.1:${PUBLISH_PORT:-58083}" \
  "postgres|127.0.0.1:${POSTGRES_PORT:-55432}" \
  "rabbitmq|amqp://127.0.0.1:${RABBITMQ_PORT:-55672}  mgmt :${RABBITMQ_MGMT_PORT:-55673}" \
  "minio S3|http://127.0.0.1:${MINIO_API_PORT:-59000}" \
  "minio console|http://127.0.0.1:${MINIO_CONSOLE_PORT:-59001}"

printf '\n'
mf_info "Креды модулей: SQL INSERT в БД review/publish (см. README модулей). Telegram/Instagram = fake."
mf_info "Live Instagram: cloudflared tunnel --url http://127.0.0.1:${MINIO_API_PORT:-59000} → S3_PUBLIC_ENDPOINT"
mf_info "Остановка: ./deploy/down.sh"
mf_summary_footer
