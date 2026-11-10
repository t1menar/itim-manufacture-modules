#!/usr/bin/env bash
# Switches module-review to the real Telegram bot (mode, token, admin and review chats, MinIO links).
# Values come from the environment or hidden prompts; secrets are never printed.
#   TELEGRAM_BOT_TOKEN  from @BotFather
#   TELEGRAM_ADMIN_IDS  optional: fixed admin ids. Leave empty to register the admin in the chat with the
#   TELEGRAM_CHAT_IDS   master token (./deploy/scripts/review-master-token.sh); the one registered admin gets the cards.
#   ./deploy/scripts/review-telegram.sh [--dry-run]
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$D/../.."
set -a; source "$ROOT/deploy/.env"; set +a
[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || { read -rs -p "Telegram bot token: " TELEGRAM_BOT_TOKEN; echo; }
export TELEGRAM_ADMIN_IDS="${TELEGRAM_ADMIN_IDS:-}" TELEGRAM_CHAT_IDS="${TELEGRAM_CHAT_IDS:-}"
export TELEGRAM_BOT_TOKEN TELEGRAM_ADMIN_IDS TELEGRAM_CHAT_IDS
if [[ "${1:-}" == "--dry-run" ]]; then python3 "$D/real-mode.py" review --dry-run; exit 0; fi
python3 "$D/real-mode.py" review | docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" \
  exec -T postgres psql -U "${POSTGRES_USER:-manufacture}" -d review -v ON_ERROR_STOP=1 -q
echo "review: telegram.mode=real"
