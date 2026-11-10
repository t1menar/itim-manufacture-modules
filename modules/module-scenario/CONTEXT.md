# module-scenario — context for agents

One module, two phases: research then script (`manufacture.scenario/1` and the post). The capture plan is not here.
Everything the owner wants (brief, palette, instructions, constraints) comes from the idea document.

Design: `docs/PIPELINE.md`. Derived from the `analysis` and `research` steps of `module-video`
(schemas `analysis.schema.json`, `research.schema.json`, prompt `prompts/research`), merged into one run and
with a knowledge cache added.

- `pipeline.py` the whole step; `script.py` the script phase; `rules.py` ported script rules (long messages, E501 off);
  `issues.py` the shared `Issue`; `service.py` the research run (pin, cache, agent loop, verify, assemble, store); `agent.py` the agent boundary
  and `Usage`; `verify.py` all deterministic checks; `sources.py` allowlist, pinning, read-only tree;
  `cache.py` cache by `(system, commit)` and keyword relevance; `models.py` tables; `schemas/` JSON Schemas.
- Tests need the `git` CLI (a real local repository is built in `tests/conftest.py`). `tests/helpers.py` has the
  scripted agent. Set `MSCENARIO_TEST_DATABASE_URL` to run on Postgres (CI does).
- After changing models: `alembic revision --autogenerate`, then `alembic check` must be clean.

Rules worth knowing:
- Only verified facts are cached. A cached fact is valid for its commit; a new commit starts empty.
- Cached ids are `f1..fk` in the request; new ids must continue after them. The agent never re-writes a cached fact.
- A web page can support a statement, never a measurement; measurements go to `capture_needs`.
- The agent never chooses the repository or ref. Change the allowlist in the environment (module-idea), not here.
- Keep this module free of the platform SDK and of any model SDK: adapters implement the Protocols.
- `tests/reference/` is the owner's hand-made reference video (scenario, research, sources). The end-to-end test builds
  a real git repository from `tests/reference/sources` and runs both phases on it.
- `mvrender` is a path dependency (`../../packages/mvrender`) used only for `timing`; it has no runtime dependencies.
