# Shared contracts (JSON Schema)

Canonical idea/topic/event shapes shared with module-video. Copies are vendored into
`video-modules/module-video/src/mvideo/ideas/schemas/`; `tests/test_ideas.py` fails if the
copies drift, so change both together. This directory must stay at the repository root
(the test looks up `contracts/` three levels above `tests/`).

| File | Purpose |
|------|---------|
| `topic.json` | Topic catalog (module-video only) |
| `idea.json` | Idea **document** in module-video |
| `events/idea.ready.json` | Orchestration payload module-video → core |
| `events/idea.status.json` | Reverse status core → module-video (`in_production` / `done` / `failed`) |

Behaviour: `video-modules/module-video/docs/IDEAS.md` (D21).

Legacy core wire schemas (`job-request`, stage outputs, …) are not kept here; they remain on
tag [`v1-legacy`](https://github.com/t1menar/itim-manufacture-modules/tree/v1-legacy) under
`core/schemas/`. The new core is https://github.com/t1menar/manufacture-core.
