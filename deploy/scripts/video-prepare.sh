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
# Optional second environment: a real Kafka broker (apache/kafka:4.4.0, KRaft, one node). Only when the image is local.
KAFKA_IMAGE=""
if docker image inspect apache/kafka:4.4.0 >/dev/null 2>&1; then
  KAFKA_IMAGE="apache/kafka@$(docker image inspect apache/kafka:4.4.0 --format '{{index .RepoDigests 0}}' | sed 's/.*@//')"
fi

echo "[4/4] module settings in core"
VALUES=$(AGENT_IMAGE="$AGENT_IMAGE" PG_IMAGE="$PG_IMAGE" KAFKA_IMAGE="$KAFKA_IMAGE" python3 - <<'PY'
import json, os
images = {"postgres17": {
    "image": os.environ["PG_IMAGE"],
    "ready_cmd": "pg_isready -U postgres",
    "version_cmd": "psql -U postgres -tAc 'SELECT version()'",
    "version_expect": "PostgreSQL 17.",
    "sessions": {"psql": {"kind": "psql", "start": "psql -X -U postgres -d {database}"}},
}}
if os.environ.get("KAFKA_IMAGE"):
    kb = "/opt/kafka/bin"
    images["kafka44"] = {
        "image": os.environ["KAFKA_IMAGE"],
        "description": "Apache Kafka 4.4.0, one KRaft node (broker and controller), PLAINTEXT on localhost:9092; "
        "CLI tools in /opt/kafka/bin; partition logs in /var/lib/kafka/data (memory-backed)",
        "hostname": "localhost",
        "env": {
            "KAFKA_HEAP_OPTS": "-Xmx512m -Xms512m", "KAFKA_NODE_ID": "1", "KAFKA_PROCESS_ROLES": "broker,controller",
            "KAFKA_LISTENERS": "PLAINTEXT://localhost:9092,CONTROLLER://localhost:9093",
            "KAFKA_ADVERTISED_LISTENERS": "PLAINTEXT://localhost:9092",
            "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
            "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1", "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
            "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1", "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS": "0",
            "KAFKA_LOG_DIRS": "/var/lib/kafka/data", "KAFKA_NUM_PARTITIONS": "1",
        },
        "tmpfs": {
            "/tmp": "size=256m,mode=1777",
            "/var/lib/kafka/data": "size=512m,uid=1000,gid=1000",
            "/opt/kafka/logs": "size=64m,uid=1000,gid=1000",
            "/opt/kafka/config": "size=8m,uid=1000,gid=1000",
        },
        "ready_cmd": f"{kb}/kafka-topics.sh --bootstrap-server localhost:9092 --list",
        "version_cmd": f"{kb}/kafka-topics.sh --version",
        "version_expect": "4.4.0",
        "sessions": {"sh": {"kind": "sh", "start": "bash"}},
    }
repos = [{"name": "postgres", "url": "https://github.com/postgres/postgres",
          "refs": ["REL_17_STABLE", "REL_16_STABLE", "master"]}]
if "kafka44" in images:
    repos.append({"name": "kafka", "url": "https://github.com/apache/kafka", "refs": ["4.4.0", "4.4", "trunk"]})
print(json.dumps({"agent": {"image": os.environ["AGENT_IMAGE"]}, "sandbox_images": images,
                  "sources": {"allowed_repos": repos}}))
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
echo "ok: agent.image=$AGENT_IMAGE sandbox=$PG_IMAGE kafka=${KAFKA_IMAGE:-none}"
