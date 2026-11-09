"""Per-step agent profile: tools and network (03 section 5.2). Limits come from settings."""

from __future__ import annotations

from dataclasses import dataclass

VALIDATE = "mcp__manufacture__validate"
READ_TOOLS = ("Read", "Glob", "Grep")
NEVER = ("Bash", "NotebookEdit", "Task")


@dataclass(frozen=True, slots=True)
class Profile:
    allowed_tools: tuple[str, ...]
    allow_domains_key: str | None  # network.allow_domains key; None: Anthropic hosts only
    capture: bool = False  # gets the sandbox_try MCP server


_SCRIPT = (*READ_TOOLS, "Write", "Edit", VALIDATE, "mcp__manufacture__estimate")
PROFILES: dict[str, Profile] = {
    "analysis": Profile((*READ_TOOLS, "Write", "WebFetch", "WebSearch", VALIDATE), "analysis"),
    "research": Profile(
        (*READ_TOOLS, "Write", "WebFetch", "WebSearch", VALIDATE, "mcp__manufacture__source_line"), "research"
    ),
    "script": Profile(_SCRIPT, None),
    "capture": Profile(("Read", "Write", "Edit", VALIDATE, "mcp__sandbox__sandbox_try"), None, capture=True),
    "package": Profile(("Read", "Write", VALIDATE), None),
    "script-revise": Profile(_SCRIPT, None),
    "trivial": Profile(("Write",), None),  # smoke test: write a file to /out
}
