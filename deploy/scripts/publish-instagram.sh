#!/usr/bin/env bash
# Switches module-publish to real Instagram publishing (mode, token and IG user id on the itim account, MinIO links).
#   INSTAGRAM_ACCESS_TOKEN  user access token;  INSTAGRAM_USER_ID  IG user id
#   ./deploy/scripts/publish-instagram.sh [--dry-run]
# The video file is read from the local MinIO and uploaded to Instagram directly (resumable upload):
# no public URL or tunnel is needed. The file stays in MinIO as the history of produced videos.
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$D/../.."
set -a; source "$ROOT/deploy/.env"; set +a
[[ -n "${INSTAGRAM_ACCESS_TOKEN:-}" ]] || { read -rs -p "Instagram access token: " INSTAGRAM_ACCESS_TOKEN; echo; }
[[ -n "${INSTAGRAM_USER_ID:-}" ]] || read -r -p "Instagram user id: " INSTAGRAM_USER_ID
export INSTAGRAM_ACCESS_TOKEN INSTAGRAM_USER_ID
if [[ "${1:-}" == "--dry-run" ]]; then python3 "$D/real-mode.py" publish --dry-run; exit 0; fi
python3 "$D/real-mode.py" publish | docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" \
  exec -T postgres psql -U "${POSTGRES_USER:-manufacture}" -d publish -v ON_ERROR_STOP=1 -q
echo "publish: instagram.mode=real"
