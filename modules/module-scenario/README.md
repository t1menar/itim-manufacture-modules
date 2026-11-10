# module-scenario

Stage `scenario` of the Manufacture video pipeline: one module with two phases, **research** then **script**.
Both phases are implemented; the real agents (Claude Agent SDK) and the platform adapter are not.

The research phase takes an idea document from `module-idea` and produces the
verified material `module-scenario` writes from: facts with exact citations, the real call path in the source,
terms to explain, viewer questions, misconceptions and what the capture step must measure.

It replaces the `analysis` and `research` steps of `module-video`; one module means one pinned source tree and one
knowledge cache for both phases. Feasibility ("can this be shown honestly?") is
now the first part of the single research run, so the idea is read once, not twice.

Python 3.12, SQLAlchemy (async), Alembic, jsonschema. No dependency on the platform SDK or on a model SDK yet:
the agent is behind a Protocol (`mscenario.agent.ResearchAgent`).

## The whole step (`ScenarioService.run(idea, step_key, revision=None)`)

Research first (keyed by the idea revision, so a review round reuses it), then the script. One pinned source tree
for both. A blocked research never reaches the script phase.

## Research phase (`ResearchService.run(idea, step_key)`)

1. A stored result for `step_key` is returned as is: a retried platform step spends nothing.
2. The source is **pinned by code**: the idea's `source_refs` (or the environment's default repository) must be in
   the environment's allowlist; the ref is fetched shallowly and unpacked to a read-only tree at a fixed commit.
3. Cached facts for `(system, commit)` that share at least two terms with the idea are offered to the agent
   (at most `cache_limit` facts and `cache_max_chars` characters).
4. The agent writes a **delta**: new facts only, ids of reused cached facts, feasibility, call path, terms,
   capture needs. A full schema is not sent to the agent, only a short hint.
5. Deterministic verification, no tokens: delta schema; code citations (file and line exist, quote is on that line
   at the pinned commit); URL citations (https, allowed domain, optional page check); no measurements as facts
   from web pages; cross references (misconceptions to facts, unique names, call path lines).
6. Errors go back to the agent as an exact list; at most `schema_retries` retries, bounded by `budget_usd`.
   `blocked` stops immediately and is not retried.
7. The assembled `manufacture.research/2` document is stored; newly verified facts enter the cache.

No database transaction is held while the agent runs.

## Script phase (`ScriptService.run(idea, research, step_key, tree, revision=None)`)

Input: the idea document (the owner's `scenario_brief`, `video_brief`, `design_notes`, `palette`, `constraints`,
`instructions.scenario`) and the research document. The agent returns `{"script": manufacture.scenario/1, "post":
manufacture.post/1}` or `{"blocked": {...}}`. Nothing is limited by this module itself: `RuleConfig.from_idea` takes
duration, lines and `reading_wps` from the idea's `constraints`, with permissive defaults.

Free deterministic checks (rules ported from `module-video`, timing from `packages/mvrender`): schema, every code
line against the pinned commit, no typed numbers, captures declared, `must_explain` terms noted, caption fit,
forbidden text, English only, hook, estimated duration. The research commit must equal `meta.system.commit`.

A reviewer's comment arrives as `Revision(visit, previous_script, previous_post, comment)`; the agent rewrites, the
same checks run, and an unchanged result is rejected. Each round is stored under its own `step_key`.

The capture plan is not produced here: it needs a sandbox to try the commands and belongs to
`module-video-generation`.

## Output

Scenario step result: `{"research": manufacture.research/2, "script": ..., "post": ...}`, or a blocked document with
`phase: research|script`.

### Research document

`manufacture.research/2`: `idea_ref`, `system`, `commit`, `facts[]` (each with `origin: cache|new`), `terms`,
`capture_needs`, `viewer_questions`, `misconceptions`, `call_path`, `knowledge {cache_hits, new_facts}`.
A blocked idea yields `manufacture.research.blocked/1` with the reason and what is missing.
Schemas: `src/mscenario/schemas/`.

## Errors for the platform adapter

| Exception | Meaning | Platform class |
|---|---|---|
| `ResearchInvalid` | output still invalid after retries | `fatal` |
| `BudgetExceeded` | the USD budget was used up | `attention` |
| `SourceNotAllowed` | repository or ref outside the allowlist, or cannot be fetched | `fatal` |
| outcome `blocked` | the idea cannot be shown honestly | `attention` (with the reason) |

## Development

```bash
cd modules/module-scenario
uv sync                       # or: python3.12 -m venv .venv and pip install the dependencies
make check                    # ruff, mypy --strict, pytest (SQLite; needs the git CLI)
MSCENARIO_TEST_DATABASE_URL=postgresql+asyncpg://... pytest   # the same tests on Postgres
alembic upgrade head          # needs MSCENARIO_DATABASE_URL
```

## Not done yet

- Real agents (Claude Agent SDK in a sandboxed container with the egress allowlist) implementing `ResearchAgent` and
  `ScriptAgent`, with prompts that read the idea's brief and `instructions`, and a model per phase.
- The `changes` diff check of module-video's revise mode (which fields the reviewer's comment may touch).
- Platform adapter on `manufacture-sdk-python` (step handler, `usage`, `step_key`).
- Page check for URL quotes, TTL for URL facts, retention of cached facts, Dockerfile, metrics.
