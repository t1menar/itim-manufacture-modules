# module-video

Stage `video`: idea → finished English video (Python 3.12).

Specification: `../docs/module-video/` (`module-video-01-description.docx` … `module-video-06-prompts.docx`). Build phases B0–B12 are in `module-video-06-prompts`.

## Status

- B0 done: service skeleton, `/info` `/health` `/ready` `/metrics`, bootstrap config, settings and contract models.
- B1 done: database `video` (8 tables, one Alembic revision run at start-up under an advisory lock), async repositories (idempotent `create_run`, leases, step upsert and reuse lookup, `add_cost`).
- B2 done: `POST /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel` (bearer auth), core client behind a swappable `CoreGateway` (HTTP contract 1), runner and worker with leases, step cache, cancel, restart recovery, usage gates. The pipeline is made of fake steps that write small files to S3 until B7/B8. `/ready` reports `auth: missing` until a job has fetched a matching credential.
- B3 done: JSON Schemas of every agent file (`src/mvideo/validate/schemas`, extracted from the contracts spec), the rules of 04 §4.3, §5.2 and §6.1, `mvideo validate DIR [--src DIR]`, and `mvrender.timing` shared by validator and renderer. The reference scenario is in `reference/create_database/` (ported by hand from the original renderer); its estimated length is within 1 % of the original.
- Known limits of B3: `caption_fit` and `note_fit` use an estimated glyph width until the renderer brings real font metrics (B4); a typed-but-never-run command (the original hook scene) cannot be expressed, so the hook scene shows an annotation line instead.
- Next: B4 renderer (needs ffmpeg).

## Develop

```bash
uv sync
make check        # ruff, mypy --strict (mvrender), import-linter, pytest (database tests need Docker)
uv run mvideo     # needs the bootstrap variables of docs 03 section 6
docker build -t module-video:dev .
```

Settings never come from the environment: they arrive with each job (settings snapshot). `/info` serves the JSON Schemas generated from `src/mvideo/settings_model.py` and `src/mvideo/contract.py`.

Note: core now carries jobs over RabbitMQ (core-04 section 15). The job intake in B2 follows whichever contract core has implemented; B1 and B3–B6 do not depend on it.
