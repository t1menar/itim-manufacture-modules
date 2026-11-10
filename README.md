# itim-manufacture-modules

Video pipeline modules for the iTim channel: idea → researched script → recorded sandbox session → rendered 1080×1920 video → Telegram review → Instagram Reels.

This repository now holds **only the modules** and the shared pieces they depend on. The original monorepo (Go core, admin-api, admin-panel and the full local stack) is preserved at tag [`v1-legacy`](https://github.com/t1menar/itim-manufacture-modules/tree/v1-legacy). The new Manufacture core is being built in [`manufacture-core`](https://github.com/t1menar/manufacture-core), with the Python SDK in [`manufacture-sdk-python`](https://github.com/t1menar/manufacture-sdk-python) and examples in [`manufacture-examples`](https://github.com/t1menar/manufacture-examples).

Start with [`AGENTS.md`](AGENTS.md) if you are working in this repo.

## Layout

| Path | Role |
|------|------|
| `video-modules/module-video/` | Stage `video` (module id `video-claude`): ideas DB and scheduler, Claude agent steps, sandbox capture, ffmpeg render. |
| `video-modules/module-review/` | Stage `review` (`review-telegram`): Telegram bot, approve/reject cards, publish notifications. |
| `video-modules/module-publish/` | Stage `publish` (`publish-instagram`): Instagram Reels via Graph API, accounts, publish ledger. |
| `contracts/` | Shared idea/topic/event JSON Schema. Vendored into module-video; a test fails on drift. Keep this directory at the repo root so that test still works. |
| `packages/mf-storage/` | Shared S3/MinIO helpers used by module-review and module-publish. |
| `deploy/` | Standalone MinIO for local module tests (`compose.minio.yml`). |
| `docs/` | Maintainer notes: decisions, content strategy, review findings. |

Paths under `video-modules/` are intentional and are not being flattened.

## Working on a module

```bash
cd video-modules/module-video    # or module-review, module-publish
uv sync && make check            # ruff, mypy, tests (import-linter in module-video)
```

Build images from the repository root (they copy `packages/mf-storage`):

```bash
docker build -f video-modules/module-review/Dockerfile -t module-review:local .
docker build -f video-modules/module-publish/Dockerfile -t module-publish:local .
```

Standalone MinIO (API `127.0.0.1:59000`, console `59001`):

```bash
docker compose -f deploy/compose.minio.yml up -d
# or: ./deploy/scripts/mfinfra-minio.sh
```

CI lives in `.github/workflows/module-*.yml` and `mf-storage.yml`. Each workflow has path filters, so a change only runs the jobs it touches.
