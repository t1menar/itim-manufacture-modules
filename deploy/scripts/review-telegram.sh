#!/usr/bin/env bash
# Switches module-review to the real Telegram bot (mode, token, admin and review chats, MinIO links).
# Values come from the environment or hidden prompts; secrets are never printed.
#   TELEGRAM_BOT_TOKEN  from @BotFather
#   TELEGRAM_ADMIN_IDS  comma-separated Telegram user ids
#   TELEGRAM_CHAT_IDS   comma-separated chat ids where review cards are posted
#   ./deploy/scripts/review-telegram.sh [--dry-run]
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$D/../.."
set -a; source "$ROOT/deploy/.env"; set +a
[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || { read -rs -p "Telegram bot token: " TELEGRAM_BOT_TOKEN; echo; }
[[ -n "${TELEGRAM_ADMIN_IDS:-}" ]] || read -r -p "Admin Telegram user ids (comma-separated): " TELEGRAM_ADMIN_IDS
[[ -n "${TELEGRAM_CHAT_IDS:-}" ]] || read -r -p "Review chat ids (comma-separated): " TELEGRAM_CHAT_IDS
export TELEGRAM_BOT_TOKEN TELEGRAM_ADMIN_IDS TELEGRAM_CHAT_IDS
if [[ "${1:-}" == "--dry-run" ]]; then python3 "$D/real-mode.py" review --dry-run; exit 0; fi
python3 "$D/real-mode.py" review | docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" \
  exec -T postgres psql -U "${POSTGRES_USER:-manufacture}" -d review -v ON_ERROR_STOP=1 -q
[[ "${S3_PUBLIC_SECURE:-0}" == "1" ]] || echo "warning: S3_PUBLIC_ENDPOINT is not a public HTTPS host; Telegram cannot fetch large videos until a tunnel is set (see deploy/README.md)" >&2
echo "review: telegram.mode=real"
