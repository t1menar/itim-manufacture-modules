#!/usr/bin/env bash
# Creates an idea in module-video and puts it in the scheduler queue (draft -> ready -> queued).
#   ./deploy/scripts/video-idea.sh "Title" "Description" "Hook line"  [topic_code]   (default topic: postgres_internals)
# The scheduler (VIDEO_IDEAS_PAUSED=0) then sends idea.ready to core, which creates the job.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; source "$ROOT/deploy/.env"; set +a
TITLE="${1:?title}"; DESC="${2:?description}"; HOOK="${3:?hook}"; TOPIC="${4:-postgres_internals}"
export TITLE DESC HOOK TOPIC
python3 - <<'PY' | docker compose -f "$ROOT/deploy/compose.yml" --env-file "$ROOT/deploy/.env" exec -T postgres \
  psql -U "${POSTGRES_USER:-manufacture}" -d video -v ON_ERROR_STOP=1 -q -t -A
import os
q = lambda s: "'" + s.replace("'", "''") + "'"
e = os.environ
print(f"""
INSERT INTO topics (code, title, description, default_tags, default_platforms)
VALUES ({q(e['TOPIC'])}, {q(e['TOPIC'])}, {q(e['TOPIC'])}, ARRAY['postgresql','databases'], ARRAY['instagram'])
ON CONFLICT (code) DO NOTHING;
WITH i AS (
  INSERT INTO ideas (topic_id, title, description, hook, language, priority, status, author)
  VALUES ((SELECT id FROM topics WHERE code = {q(e['TOPIC'])}), {q(e['TITLE'])}, {q(e['DESC'])}, {q(e['HOOK'])},
          'en', 10, 'draft', 'deploy')
  RETURNING id)
UPDATE ideas SET status = 'ready', ready_at = now() WHERE id = (SELECT id FROM i);
UPDATE ideas SET status = 'queued', queued_at = now()
 WHERE id = (SELECT max(id) FROM ideas WHERE author = 'deploy') AND status = 'ready'
RETURNING 'queued idea ' || id;
""")
PY
