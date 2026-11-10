# itim-manufacture-modules

Video pipeline modules for the iTim channel: idea → researched script → recorded sandbox session → rendered 1080×1920 video → Telegram review → Instagram Reels.

This repository now holds **only the modules** and the shared pieces they depend on. The original monorepo (Go core, admin-api, admin-panel and the full local stack) is preserved at tag [`v1-legacy`](https://github.com/t1menar/itim-manufacture-modules/tree/v1-legacy). The new Manufacture core is being built in [`manufacture-core`](https://github.com/t1menar/manufacture-core), with the Python SDK in [`manufacture-sdk-python`](https://github.com/t1menar/manufacture-sdk-python) and examples in [`manufacture-examples`](https://github.com/t1menar/manufacture-examples).

Start with [`AGENTS.md`](AGENTS.md) if you are working in this repo.

## Layout

| Path | Role |
|------|------|
| `modules/module-idea/` | New pipeline, stage `idea`: idea backlog, playlists, rubrics, scheduling, cost and outcomes. |
| `modules/module-scenario/` | New pipeline, stage `scenario`: research (verified facts, knowledge cache) and the scenario in one module. See `docs/PIPELINE.md`. |
| `modules/module-video/` | Stage `video` (module id `video-claude`): ideas DB and scheduler, Claude agent steps, sandbox capture, ffmpeg render. |
| `modules/module-review/` | Stage `review` (`review-telegram`): Telegram bot, approve/reject cards, publish notifications. |
| `modules/module-publish/` | Stage `publish` (`publish-instagram`): Instagram Reels via Graph API, accounts, publish ledger. |
| `packages/mvrender/` | Standalone renderer and timing library for scenarios. |
| `packages/mf-storage/` | Shared S3/MinIO helpers used by module-review and module-publish. |
| `deploy/` | Standalone MinIO for local module tests (`compose.minio.yml`). |
| `docs/` | Maintainer notes: decisions, content strategy, review findings. |

Each module lives in its own package `modules/<module_name>/`.

## Working on a module

```bash
cd modules/module-video    # or module-review, module-publish
uv sync && make check            # ruff, mypy, tests (import-linter in module-video)
```

Build images from the repository root (they copy `packages/mf-storage`):

```bash
docker build -f modules/module-review/Dockerfile -t module-review:local .
docker build -f modules/module-publish/Dockerfile -t module-publish:local .
```

Standalone MinIO (API `127.0.0.1:59000`, console `59001`):

```bash
docker compose -f deploy/compose.minio.yml up -d
# or: ./deploy/scripts/mfinfra-minio.sh
```

CI lives in `.github/workflows/module-*.yml` and `mf-storage.yml`. Each workflow has path filters, so a change only runs the jobs it touches.
