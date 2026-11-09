# module-video

Stage `video`: idea → finished English video (Python 3.12).

Specification: `../docs/module-video/` (`module-video-01-description.docx` … `module-video-06-prompts.docx`). Build phases B0–B12 are in `module-video-06-prompts`.

## Status

- B0 done: service skeleton, `/info` `/health` `/ready` `/metrics`, bootstrap config, settings and contract models.
- B1 done: database `video` (8 tables, one Alembic revision run at start-up under an advisory lock), async repositories (idempotent `create_run`, leases, step upsert and reuse lookup, `add_cost`).
- B2 done: `POST /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel` (bearer auth), core client behind a swappable `CoreGateway` (HTTP contract 1), runner and worker with leases, step cache, cancel, restart recovery, usage gates. The pipeline is made of fake steps that write small files to S3 until B7/B8. `/ready` reports `auth: missing` until a job has fetched a matching credential.
- B3 done: JSON Schemas of every agent file (`src/mvideo/validate/schemas`, extracted from the contracts spec), the rules of 04 §4.3, §5.2 and §6.1, `mvideo validate DIR [--src DIR]`, and `mvrender.timing` shared by validator and renderer. The reference scenario is in `reference/create_database/` (ported by hand from the original renderer); its estimated length is within 1 % of the original.
- Known limits of B3: `caption_fit` and `note_fit` use an estimated glyph width until the renderer brings real font metrics (B4); a typed-but-never-run command (the original hook scene) cannot be expressed, so the hook scene shows an annotation line instead.
- B4 done (stills): `mvrender` resolves script + capture + source into frames: palette, fonts (Inter and JetBrains Mono in `fonts/`, copied to `/usr/share/fonts/manufacture` in the image), layout, safe zone, terminal, debugger, diagram elements, glyph and safe-zone checks, `mvrender preview DIR --src DIR --at ...`, `mvrender sheet` (contact sheet with the safe-zone overlay). The reference renders from `reference/create_database/` with source excerpts in `reference/create_database/sources/`; approved frames are in `tests/approved/` (SSIM >= 0.98).
- B5 done (video and sound): `mvrender render DIR --src DIR --out OUT` renders `video.en.mp4`, `cover.en.jpg` and `sfx.en.wav`. Cues come from animation events (`cues.py`, one cue per event, checked within one frame), sound is synthesized with seeded randomness (`sfx.py`), chunks are encoded in parallel by single-threaded x264 and joined with `-c copy` (`encode.py`; 1, 4 and 8 workers give identical bytes). The sound is leveled to -14 LUFS under a -1 dBTP ceiling with a limiter and measurement loop (sparse effects cannot reach the target by linear gain, so `loudnorm` is used only to measure). Reference: 9817 frames in 181 s on 8 workers (1.11 s per video second), -14.3 LUFS, -1.8 dBTP. ffmpeg comes from `$FFMPEG`, PATH or the dev dependency `imageio-ffmpeg`; the image installs it with apt.
- B6 done (sandbox): `mvideo.sandbox` has `templates.py` (container spec from settings: digest required, network none, read-only root, tmpfs, cap_drop ALL, no-new-privileges, no binds, no privileges), `sessions.py` (long-lived psql on a pty with sentinel prompts, sh on pipes with an `$?` sentinel, merged output) and `executor.py` (plan to `capture.json` through the Docker SDK at `DOCKER_HOST`; containers removed after the run). Docker tests are marked `docker` (`uv run pytest -m docker`; they need a daemon and the local image `postgres:17`, otherwise they skip). Image entries may set `exec_user` (session user, `postgres` for the Postgres image). `ready_cmd` for Postgres must use TCP (`pg_isready -h 127.0.0.1 -U postgres`), because the entrypoint's temporary server listens on the socket only. The reference plan was corrected: a hidden `ROLLBACK;` after the failed transaction, and `n_relations` counts non-shared relations with storage (222), not all of `pg_class` (415).
- Next: B5 cues, sound, parallel encode and loudness (needs ffmpeg).

## Develop

```bash
uv sync
make check        # ruff, mypy --strict (mvrender), import-linter, pytest (database tests need Docker)
uv run mvideo     # needs the bootstrap variables of docs 03 section 6
docker build -t module-video:dev .
```

Settings never come from the environment: they arrive with each job (settings snapshot). `/info` serves the JSON Schemas generated from `src/mvideo/settings_model.py` and `src/mvideo/contract.py`.

Note: core now carries jobs over RabbitMQ (core-04 section 15). The job intake in B2 follows whichever contract core has implemented; B1 and B3–B6 do not depend on it.
