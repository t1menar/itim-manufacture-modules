# Shared contracts (JSON Schema)

Cross-service shapes not yet folded into `core/schemas/`.

| File | Purpose |
|------|---------|
| `topic.json` | Topic catalog (module-video only) |
| `idea.json` | Idea **document** in module-video (not stored in core) |
| `events/idea.ready.json` | Orchestration payload module-video → core |
| `events/idea.status.json` | Reverse status core → module-video (`in_production` / `done` / `failed`) |

Behaviour: `module-video/docs/IDEAS.md` (D21).
