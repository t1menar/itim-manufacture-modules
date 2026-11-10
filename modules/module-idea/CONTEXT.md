# module-idea — context for agents

Owns the idea backlog of the new pipeline (idea → research → scenario → review → video-generation → review →
publisher). Design: `docs/PIPELINE.md`; what it needs from the platform: `docs/PLATFORM_REQUIREMENTS.md`.
Derived from the ideas part of `module-video` (D21) with playlists, rubrics, environments, cost and outcomes added.

- `src/midea/models.py` tables (portable types: Postgres in production, SQLite in unit tests).
- `src/midea/service.py` all logic; `status.py` the status machine; `api.py` HTTP; `app.py` wiring.
- `migrations/` Alembic. After changing models: `alembic revision --autogenerate`, then `alembic check` must be clean.
- Tests run on SQLite; set `MIDEA_TEST_DATABASE_URL` to run them on Postgres (CI does).

Rules worth knowing:
- Only content fields bump `rev` and write a snapshot; priority, status and playlist membership do not.
  The snapshot's `playlists` are those at the time of the revision.
- An idea in production (`dispatched`, `in_production`) cannot be edited or deleted.
- Run events are idempotent and monotonic; cost is the sum over `idea_runs`.
- Keep this module free of the platform SDK: add the adapter as a separate package/file calling `IdeaService`.
