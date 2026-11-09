# module-video

Stage `video`: idea → finished English video (Python 3.12).

Specification: `../docs/module-video/` (`module-video-01-description.docx` … `module-video-06-prompts.docx`). Build phases B0–B12 are in `module-video-06-prompts`.

## Status

- B0 done: service skeleton, `/info` `/health` `/ready` `/metrics`, bootstrap config, settings and contract models.
- B1 done: database `video` (8 tables, one Alembic revision run at start-up under an advisory lock), async repositories (idempotent `create_run`, leases, step upsert and reuse lookup, `add_cost`).
- Next: B2 job API (see the messaging note below), B3 schemas and validator, B4 renderer.

## Develop

```bash
uv sync
make check        # ruff, mypy --strict (mvrender), import-linter, pytest (database tests need Docker)
uv run mvideo     # needs the bootstrap variables of docs 03 section 6
docker build -t module-video:dev .
```

Settings never come from the environment: they arrive with each job (settings snapshot). `/info` serves the JSON Schemas generated from `src/mvideo/settings_model.py` and `src/mvideo/contract.py`.

Note: core now carries jobs over RabbitMQ (core-04 section 15). The job intake in B2 follows whichever contract core has implemented; B1 and B3–B6 do not depend on it.
