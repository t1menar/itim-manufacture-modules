# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Core stack on main

Landing PR merged: core slices #3–#5 (through admin republish `62f133c`) are on `main` via merge commit of `core/land-on-main` (`d2d260a`).

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 / P2 / C38 | Admin-only manual republish with reason |
| D16 / C40 | Runtime prompts owned by module-video |
| **D19 / P1 / C39** | **Title, description, topics + per-platform caption/hashtags come from module-video in required `variants[].metadata`. No separate `content-claude` / module-content stage.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | On `main` through republish; D19 snapshot + schema on PR #8 | Gaps: full JSON Schema on result, review→intents wiring |
| module-video | Python | Owner through B8 on `main` (`4dee415` metadata, `3693105` B8) | Emits `variants[].metadata` (D19) |
| module-review | Python | PR #6 skeleton | Base `main`; not merged |
| module-publish | Python | Not started | |
| module-content | — | **Rejected (D19)** | Do not implement |
| admin-api | Go | Not started | |
| admin-panel | React | Deferred (D13) | |

## D19 / C39 metadata compatibility (PR #8 vs module-video)

Checked against `4dee415` / `3693105` (contract `Metadata` / `PlatformMetadata`, `fake_finalize`, `build_metadata`):

| Field | module-video | `stage-video-output.json` / core snapshot | Match |
|-------|--------------|-------------------------------------------|-------|
| `title` (minLength 1) | yes | required | yes |
| `description` | yes | required | yes |
| `topics[]` | yes | required | yes |
| `platforms.<p>.caption` | yes | required | yes |
| `platforms.<p>.hashtags` (`^#\S+$`) | yes (`#…`) | required + pattern | yes |
| `platforms.<p>.fields` | optional | optional | yes |

**No core/spec change required for metadata.** Video module code not touched.

### Note (not blocking #8; fix on core side when enabling full schema validation)

`contact_sheet` / `cover`: module-video sends **s3:// strings**; core schema currently types them as artifact **objects** `{ref, sha256?}`. Metadata path and `snapshotVideoRevision` accept either. Align schema to `string | object` in the core-gaps PR before strict JSON Schema validation of video results, otherwise e2e would 422.

## Open core gaps (next PRs, do not merge without owner)

1. Full JSON Schema validation of stage `output` on result callback → 422 `output_invalid`.
2. Review `approved` → idempotent generation-1 `publish_intents` (variant × accounts) + outbox publish job in the same transaction.
3. Instagram caption/hashtag limits in `system_settings` (small).
4. module-publish skeleton (fake Instagram Login only).
