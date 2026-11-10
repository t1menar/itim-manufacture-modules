# module-idea

Stage `idea` of the Manufacture video pipeline: the backlog where the owner enters ideas, groups them into
playlists and rubrics, and from which the pipeline takes the next idea to produce. Also keeps the cost of
every idea and the performance of the published video.

Python 3.12, FastAPI, SQLAlchemy (async), Alembic. No dependency on the platform SDK yet: all logic is in
`IdeaService`; the HTTP API and the future platform adapter are thin callers.

## Concepts

| Entity | Meaning |
|---|---|
| `environments` | Where a video is recorded: sandbox image, version expectation, allowed source repositories. |
| `rubrics` | Recurring format (race, predict the output, break it, myth vs reality, cost) with a scenario template. |
| `playlists` / `playlist_ideas` | Topic series. An idea may be in several playlists; order is by `sort_order` then `position`. |
| `ideas` | The idea and the context a good video needs (see below). Status: draft, queued, dispatched, in_production, done, failed, archived. |
| `idea_revisions` | Immutable document per revision, `idea:<id>:v<rev>`. The pipeline always works on one revision. |
| `idea_runs` | One platform run of an idea; cost is stored per run, so replays are idempotent. |
| `idea_outcomes` | Views, saves, shares, follows of the published video. |

Context fields of an idea beyond title and description: `key_takeaway`, `hook`, `audience`, `rubric_code`,
`environment`, `depth` (broad/deep), `difficulty`, `demo_commands`, `expected_result`, `must_show`,
`must_avoid`, `source_refs`, `references`, `constraints`, `target_duration_s`, `priority`, `notes`.

### What the owner specifies per idea (nothing is hard-coded in later stages)

| Field | Used by |
|---|---|
| `scenario_brief` | The short script: what happens, in order. The scenario stage expands it. |
| `video_brief` | How the video should feel: pace, tone, format, ending. |
| `design_notes`, `palette` | Visual wishes in words and colour token overrides (`token -> #RRGGBB`) for the renderer. |
| `constraints` | Optional limits: `duration_s {min,max}`, `max_scenes`, `hook_max_lines`, `caption_max_lines`, `note_max_lines`, `reading_wps`, `allowed_domains`, `voice`, `max_cost_usd`. Unknown keys pass through. |
| `instructions` | Extra instructions for a stage's agent: `research`, `scenario`, `video` (up to 4000 characters each). |

Stages read what they understand and fall back to their own defaults; the idea overrides them.
All of it is part of the revision document, so a change creates a new revision.

An idea can be queued only when it has `key_takeaway`, a rubric, an environment and a real description:
a weak idea is caught here, not after the expensive steps.

## Scheduling

`IdeaService.pick_next(SchedulerPolicy(max_in_flight, min_interval_s, paused))` returns queued ideas by
priority, then playlist order. Ideas only in inactive playlists or on inactive environments are skipped.
`dispatch(idea_id, run_id)` binds an idea to a platform run. `apply_run_event(RunEvent)` applies
`running | succeeded | failed | cancelled`: idempotent, monotonic, adds the cost. `release_stale` returns ideas
stuck in `dispatched` to the queue.

## HTTP API (`/v1`)

`PUT /environments`, `PUT /rubrics`, `POST|GET /playlists`, `GET|PATCH /playlists/{code}`,
`POST /playlists/{code}/ideas`, `DELETE /playlists/{code}/ideas/{id}`, `PUT /playlists/{code}/order`,
`POST|GET /ideas`, `GET|PATCH|DELETE /ideas/{id}`, `POST /ideas/{id}/status`, `GET /ideas/{id}/document`,
`POST /ideas/{id}/outcomes`, `GET /stats?group_by=rubric|depth|playlist|environment`.
Errors are `application/problem+json`. Set `MIDEA_API_TOKEN` to require a bearer token; bind to loopback.

## Configuration

| Variable | |
|---|---|
| `MIDEA_DATABASE_URL` | `postgresql+asyncpg://...` (required) |
| `MIDEA_API_TOKEN` | optional bearer token |

## Development

```bash
cd modules/module-idea
uv sync                      # or: python3.12 -m venv .venv && pip install -e . plus the dev group
make check                   # ruff, mypy --strict, pytest (SQLite)
MIDEA_TEST_DATABASE_URL=postgresql+asyncpg://... pytest   # the same tests on Postgres
alembic upgrade head         # needs MIDEA_DATABASE_URL
uvicorn --factory midea.app:create_app --host 127.0.0.1 --port 58085
```

## Not done yet

Platform adapter on `manufacture-sdk-python` (source that emits `run.requested` with `priority` and
`dedup_key=idea_ref`, subscriber of `run.finished`), Dockerfile, metrics, retention of `idea_status_log`.
