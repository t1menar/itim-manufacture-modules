# contracts + packages — context for agents

`contracts/` holds JSON Schemas shared with module-video: `topic.json`, `idea.json` (idea document,
lives only in module-video), `events/idea.ready.json` (module-video → core orchestration payload),
`events/idea.status.json` (core → module-video `in_production|done|failed`). They are vendored into
`modules/module-video/src/mvideo/ideas/schemas/`; a test fails when copies drift, so change
both together. Keep this directory at the repo root.

Legacy core wire schemas lived in `core/schemas/` and are available on tag `v1-legacy`. The new
core is https://github.com/t1menar/manufacture-core.

`packages/mf-storage/` — Python helpers: parse `s3://<bucket>/<production_id>/<stage>/<attempt>/…`,
presigned GET with separate internal/public endpoints (SigV4 host). Used by module-review and
module-publish; env `S3_ENDPOINT|ACCESS_KEY|SECRET_KEY|BUCKET|SECURE|PUBLIC_ENDPOINT|PUBLIC_SECURE`.
`cd packages/mf-storage && uv sync && uv run pytest`.
