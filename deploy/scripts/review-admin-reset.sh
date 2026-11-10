#!/usr/bin/env bash
# Forgets the registered Telegram admin (and optionally issues a new master token), so another person can register.
#   ./deploy/scripts/review-admin-reset.sh [--new-token]    then: docker compose restart module-review
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; source "$ROOT/deploy/.env"; set +a
SQL="DELETE FROM module_settings WHERE key = 'telegram.registered_admin';"
[[ "${1:-}" == "--new-token" ]] && SQL+=" DELETE FROM module_secrets WHERE key = 'telegram.master_token';"
docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" exec -T postgres \
  psql -U "${POSTGRES_USER:-manufacture}" -d review -v ON_ERROR_STOP=1 -q -c "$SQL"
docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" restart module-review >/dev/null
echo "admin reset; module-review restarted"
