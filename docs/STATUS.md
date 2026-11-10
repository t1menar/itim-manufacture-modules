# itim-manufacture-modules — status

_Last updated: 2026-11-10 (Europe/Stockholm)._

This repository is now **modules-only**. The Go core, admin-api, admin-panel and the full local
stack were removed from `main`; that tree is frozen at tag
[`v1-legacy`](https://github.com/t1menar/itim-manufacture-modules/tree/v1-legacy) (`f88ce1e`).
The new core is https://github.com/t1menar/manufacture-core (with
[manufacture-sdk-python](https://github.com/t1menar/manufacture-sdk-python) and
[manufacture-examples](https://github.com/t1menar/manufacture-examples)).

## On main

Domain (video) modules live in `video-modules/`: `module-video`, `module-review`, `module-publish`.
Shared pieces kept at the top level: `contracts/` (idea/topic/event schemas; module-video drift
test), `packages/mf-storage/` (S3 helpers for review and publish), `deploy/` (standalone MinIO).
Module ids, image names and service names are unchanged. Paths under `video-modules/` are not
being flattened.

#7–#37 were merged in the former monorepo, including #35 (B6, no double posts), #36 (B5, idea
parking in the legacy core) and #37 (move of the Python modules into `video-modules/`).

The video pipeline on this `main` is not expected to run end-to-end until the modules are ported
onto the new SDK.

## Accepted decisions that still apply to the modules

| # | Decision |
|---|----------|
| D21 | Ideas and topics live in module-video; core (legacy or new) keeps only an opaque `idea_ref`. Schemas: `contracts/`. See `video-modules/module-video/docs/IDEAS.md`. |
| D22 | Opaque content revisions (`content_revisions`: blob + sha256) — a legacy-core concern; modules still emit opaque refs. |
| D23 | Publish intents are owned by module-publish. |
| B6 | `publish_ledger` in module-publish: one row per (intent, account). `published` → retry returns the stored post; `publishing`/`unknown` → only reconcile, never post again; `failed` → may be posted by the next attempt. `media_publish` is never retried on 5xx/transport errors. Fence right before `media_publish` (`ledger_arm`). |

Historical admin/core decisions (D18, D20, D24, B5) and the old admin-panel PR list are in the
docs on `v1-legacy`.

## Local deploy

Standalone MinIO: `docker compose -f deploy/compose.minio.yml up -d` (or
`./deploy/scripts/mfinfra-minio.sh`). Default ports 59000/59001.

The former `./deploy/up.sh` stack (Postgres, RabbitMQ, core, modules, admin-api + panel,
register+activate) is on `v1-legacy` only.

## module-publish: no double posts (B6)

- `publish_ledger` (migration `0005`): one row per (intent, account). `published` → a retry returns the stored post (no API call); `publishing`/`unknown` → only reconcile (container `status_code`, recent media by caption and time), never post again; `failed` (container ERROR/EXPIRED or a definite 4xx) → may be posted by the next attempt.
- `media_publish` is never retried on 5xx/transport errors: outcome unknown → reconcile → else `status=unknown` (`publish_outcome_unknown`).
- Fence right before `media_publish` (`ledger_arm`): the run must be live with the same fence, not cancelled, and at least 30 s before the job deadline. A timed-out, cancelled or superseded (higher fence for the same job) run cannot post.

## module-video

Known issue (still open): heartbeat of `video-claude` can go `down` if the background loop does
not refresh `last_seen_at` (after ~90 s the core marks it down). That has to be fixed in
module-video; do not start that work unless the owner asks.
