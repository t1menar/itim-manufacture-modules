#!/usr/bin/env bash
# Prints the master token the Telegram admin sends to the bot to register (generated once by module-review).
# The token exists after module-review has started in real mode (review-telegram.sh).
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; source "$ROOT/deploy/.env"; set +a
T=$(docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" exec -T postgres \
  psql -U "${POSTGRES_USER:-manufacture}" -d review -tAc "SELECT value FROM module_secrets WHERE key = 'telegram.master_token'")
[[ -n "$T" ]] || { echo "no master token yet: run review-telegram.sh and restart module-review" >&2; exit 1; }
echo "$T"
