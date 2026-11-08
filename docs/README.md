# Manufacture — specifications

Specifications for the Manufacture system (iTim channel). All specs are Word documents built from sources in `tools/specgen/` (see `tools/specgen/AUTHORING.md`).

`Manufacture-Overview.docx` — abstract, processes, architecture, decisions, open questions.

Each service folder holds six documents, named `<service>-0N-<name>.docx`:

| # | Document | Content |
|---|---|---|
| 01 | description | purpose, responsibilities, place in the system, glossary, scope |
| 02 | requirements | functional and non-functional requirements with acceptance checks |
| 03 | technical | stack, structure, data model, configuration, deployment, observability, security, testing |
| 04 | contracts | APIs exposed and consumed, schemas, errors, settings schema |
| 05 | process | internal flows, state machines, retries, recovery |
| 06 | prompts | runtime prompts for Claude and build prompts for Claude Code |

| Folder | Service |
|---|---|
| `core/` | pipeline engine and module registry (Go) |
| `admin-api/` | administrative gateway (Go) |
| `admin-panel/` | web client (React + TypeScript) |
| `module-video/` | stage `video`: idea → research → script → capture → rendered English video (Python) |
| `module-review/` | stage `review`: Telegram review bot (Python) |
| `module-publish/` | stage `publish`: Instagram Reels and later platforms (Python) |

Each folder has the same name as the service folder at the root of this repository (`github.com/t1menar/manufacture`).

Rebuild everything:

```bash
cd tools/specgen && npm install && npm run build
```
