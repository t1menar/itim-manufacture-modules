#!/usr/bin/env bash
# Prepares module-video for real jobs: agent image through the local registry (digest),
# sandbox image digests, and module settings of `video-claude` in the core database.
# Idempotent. Run after ./deploy/up.sh. Secrets are not touched or printed.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env")
set -a; source "$ROOT/deploy/.env"; set +a
PGU="${POSTGRES_USER:-manufacture}"
MODULE_ID="${VIDEO_MODULE_ID:-video-claude}"

echo "[1/4] agent image"
if ! docker image inspect video-agent:dev >/dev/null 2>&1; then
  docker build -t video-agent:dev -f "$ROOT/module-video/agent/Dockerfile" "$ROOT/module-video"
fi

echo "[2/4] local registry and digest"
"${COMPOSE[@]}" up -d registry >/dev/null
for _ in $(seq 1 30); do curl -sf http://127.0.0.1:5000/v2/ >/dev/null && break; sleep 1; done
docker tag video-agent:dev localhost:5000/video-agent:dev
AGENT_REF=$(docker push localhost:5000/video-agent:dev | awk '/digest: sha256:/ {print $3}')
[[ -n "$AGENT_REF" ]] || { echo "no digest from push" >&2; exit 1; }
AGENT_IMAGE="localhost:5000/video-agent@${AGENT_REF}"

echo "[3/4] sandbox image digest (postgres:17)"
docker image inspect postgres:17 >/dev/null 2>&1 || docker pull postgres:17 >/dev/null
PG_DIGEST=$(docker image inspect postgres:17 --format '{{index .RepoDigests 0}}' | sed 's/.*@//')
PG_IMAGE="postgres:17@${PG_DIGEST}"

echo "[4/4] module settings in core"
VALUES=$(AGENT_IMAGE="$AGENT_IMAGE" PG_IMAGE="$PG_IMAGE" python3 - <<'PY'
import json, os
print(json.dumps({
    "agent": {"image": os.environ["AGENT_IMAGE"]},
    "sandbox_images": {"postgres17": {
        "image": os.environ["PG_IMAGE"],
        "ready_cmd": "pg_isready -U postgres",
        "version_cmd": "psql -U postgres -tAc 'SELECT version()'",
        "version_expect": "PostgreSQL 17.",
        "sessions": {"psql": {"kind": "psql", "start": "psql -X -U postgres -d {database}"}},
    }},
}))
PY
)
"${COMPOSE[@]}" exec -T postgres psql -U "$PGU" -d core -v ON_ERROR_STOP=1 -v mid="$MODULE_ID" -v vals="$VALUES" <<'SQL'
BEGIN;
UPDATE module_settings SET is_current = false WHERE module_id = :'mid' AND is_current;
INSERT INTO module_settings (module_id, version, values, valid, comment, author, is_current)
SELECT :'mid', COALESCE(MAX(version), 0) + 1, :'vals'::jsonb, true, 'video-prepare.sh', 'deploy', true
FROM module_settings WHERE module_id = :'mid';
COMMIT;
SQL
echo "ok: agent.image=$AGENT_IMAGE sandbox=$PG_IMAGE"
