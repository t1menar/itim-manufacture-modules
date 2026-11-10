#!/usr/bin/env bash
# Creates an idea in module-video and puts it straight into the scheduler queue (status queued).
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
-- One statement: a data-modifying CTE cannot see its own INSERT, so a follow-up UPDATE of the
-- new row would match nothing and leave the idea in draft. Author must match ^(tg|db|user):.+$
-- (idea schema), otherwise the scheduler fails the idea with idea_invalid.
INSERT INTO ideas (topic_id, title, description, hook, language, priority, status, author, ready_at, queued_at)
VALUES ((SELECT id FROM topics WHERE code = {q(e['TOPIC'])}), {q(e['TITLE'])}, {q(e['DESC'])}, {q(e['HOOK'])},
        'en', 10, 'queued', 'db:deploy', now(), now())
RETURNING 'queued idea ' || id;
""")
PY
