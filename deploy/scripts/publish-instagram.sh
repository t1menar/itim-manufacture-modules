#!/usr/bin/env bash
# Switches module-publish to real Instagram publishing (mode, token and IG user id on the itim account, MinIO links).
#   INSTAGRAM_ACCESS_TOKEN  user access token;  INSTAGRAM_USER_ID  IG user id
#   ./deploy/scripts/publish-instagram.sh [--dry-run]
# Instagram downloads the video by a public HTTPS URL, so S3_PUBLIC_ENDPOINT must be a tunnel host
# and S3_PUBLIC_SECURE=1 (deploy/README.md).
set -Eeuo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$D/../.."
set -a; source "$ROOT/deploy/.env"; set +a
[[ -n "${INSTAGRAM_ACCESS_TOKEN:-}" ]] || { read -rs -p "Instagram access token: " INSTAGRAM_ACCESS_TOKEN; echo; }
[[ -n "${INSTAGRAM_USER_ID:-}" ]] || read -r -p "Instagram user id: " INSTAGRAM_USER_ID
export INSTAGRAM_ACCESS_TOKEN INSTAGRAM_USER_ID
if [[ "${1:-}" == "--dry-run" ]]; then python3 "$D/real-mode.py" publish --dry-run; exit 0; fi
[[ "${S3_PUBLIC_SECURE:-0}" == "1" ]] || { echo "S3_PUBLIC_ENDPOINT must be a public HTTPS tunnel host with S3_PUBLIC_SECURE=1 in deploy/.env" >&2; exit 1; }
python3 "$D/real-mode.py" publish | docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" \
  exec -T postgres psql -U "${POSTGRES_USER:-manufacture}" -d publish -v ON_ERROR_STOP=1 -q
echo "publish: instagram.mode=real"
