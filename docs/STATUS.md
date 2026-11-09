# Manufacture — module / service status

_Last updated: 2026-11-09 (Europe/Stockholm)._

## Core stack on main

Landing PR merged: core slices #3–#5 (through admin republish `62f133c`) are on `main` via merge commit of `core/land-on-main`.

## Accepted decisions (recent)

| # | Decision |
|---|----------|
| D18 / P2 / C38 | Admin-only manual republish with reason |
| D16 / C40 | Runtime prompts owned by module-video |
| **D19 / P1 / C39** | **Title, description, topics + per-platform caption/hashtags come from module-video in required `variants[].metadata`. No separate `content-claude` / module-content stage.** |

## Service table

| Service | Lang | Status | Notes |
|---------|------|--------|-------|
| core | Go | On `main` through republish + video→content_revision snapshot (D19) | |
| module-video | Python | Owner B0–B6+ on `main` | Must add `metadata` to result (see below) |
| module-review | Python | PR #6 skeleton | Base retargeted to `main` |
| module-publish | Python | Not started | |
| module-content | — | **Rejected (D19)** | Do not implement |
| admin-api | Go | Not started | |
| admin-panel | React | Deferred (D13) | |

## Gap: module-video must add for D19/C39

Core now **requires** `variants[].metadata` when accepting a video/revise result (creates `content_revisions`). The current video module code does **not** emit it yet.

Owner should add (do not treat this list as implemented):

1. **`Variant.metadata`** in `src/mvideo/contract.py` (`StageOutput`): required object with `title`, `description`, `topics[]`, `platforms.<platform>.{caption, hashtags[], fields?}`.
2. **Package / finalize path** (`fake_finalize` and the real package agent): fill `metadata` (and keep `post` as the Instagram projection if still used for checks).
3. **`/info` output_schema** will update automatically from the Pydantic model.
4. **Tests**: fixture outputs and fake finalize must include `metadata` or core will answer `422 output_invalid`.

Until then, e2e video→core result callbacks that omit `metadata` fail validation on core.
