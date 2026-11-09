# Shared contracts (JSON Schema)

Cross-service shapes that are not yet folded into `core/schemas/`.

| File | Purpose |
|------|---------|
| `topic.json` | Topic catalog entry owned by module-video (D21) |
| `idea.json` | Immutable idea snapshot published to core |
| `events/idea.ready.json` | Payload of AMQP `idea.ready` |

Authoritative behaviour: `module-video/docs/IDEAS.md`. When core implements the consumer, promote copies into `core/schemas/` and extend the envelope `type` enum.
