#!/usr/bin/env bash
# Stores the Claude credential of module-video in its `credentials` table (database `video`).
# The value is read without echo from the prompt (or from CLAUDE_TOKEN) and goes to psql through stdin,
# so it is neither printed, logged, nor visible in a process list.
#   ./deploy/scripts/video-credential.sh [REF] [kind]    defaults: CLAUDE_OAUTH_TOKEN claude_oauth_token
#   kind: claude_oauth_token (subscription) | anthropic_api_key
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; source "$ROOT/deploy/.env"; set +a
REF="${1:-CLAUDE_OAUTH_TOKEN}"; KIND="${2:-claude_oauth_token}"
VALUE="${CLAUDE_TOKEN:-}"
if [[ -z "$VALUE" ]]; then read -rs -p "Value for $REF ($KIND): " VALUE; echo; fi
[[ -n "$VALUE" ]] || { echo "empty value" >&2; exit 1; }
export REF KIND VALUE
python3 - <<'PY' | docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" exec -T postgres \
  psql -U "${POSTGRES_USER:-manufacture}" -d video -v ON_ERROR_STOP=1 -q
import os
q = lambda s: "'" + s.replace("'", "''") + "'"
print(f"INSERT INTO credentials (ref, kind, value, note, updated_by) VALUES "
      f"({q(os.environ['REF'])}, {q(os.environ['KIND'])}, {q(os.environ['VALUE'])}, 'deploy', 'deploy') "
      f"ON CONFLICT (ref) DO UPDATE SET kind = EXCLUDED.kind, value = EXCLUDED.value, "
      f"updated_by = 'deploy', updated_at = now();")
PY
echo "stored $REF ($KIND)"
