"""The agent boundary. The service owns everything deterministic; an agent only reads and writes the delta.

A real implementation (Claude Agent SDK in a sandboxed container) lives outside this package and implements
`ResearchAgent`. Tests use scripted agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

# What the agent is shown instead of the whole JSON Schema (cheaper, and the validator is the authority).
SCHEMA_HINT = """\
Write one JSON object, format "manufacture.research.delta/1":
- feasibility {decision: go|blocked, reason, missing[], suggestion}: blocked when the idea cannot be shown honestly.
- facts[]: ONLY new facts {id, text<=300 chars, cite}; ids continue after the last cached id.
  cite is {file, line, quote} (quote copied from that line of the pinned source) or {url, quote} (allowed domains).
- reused_facts[]: ids of cached facts you rely on (do not repeat their text).
- viewer_questions[] {question, source url}, misconceptions[] {claim, truth, facts[] ids},
  call_path[] {function, file, line_start, line_end, role, key_lines[] {n, expect, why}},
  terms[] {term, explain<=140, must_explain, aliases[]}, capture_needs[] {name snake_case, meaning, how}.
Measurements (sizes, timings, counts that depend on the running system) are capture_needs, never facts.
"""


@dataclass(frozen=True, slots=True)
class Usage:
    cost_usd: Decimal = Decimal(0)
    tokens: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> {input, output, cache_read, cache_write}

    def __add__(self, other: Usage) -> Usage:
        merged: dict[str, dict[str, int]] = {m: dict(t) for m, t in self.tokens.items()}
        for model, counts in other.tokens.items():
            slot = merged.setdefault(model, {})
            for k, v in counts.items():
                slot[k] = slot.get(k, 0) + v
        return Usage(self.cost_usd + other.cost_usd, merged)

    def as_dict(self) -> dict[str, Any]:
        return {"cost_usd": str(self.cost_usd), "tokens": self.tokens}


@dataclass(frozen=True, slots=True)
class CachedFact:
    id: str  # id inside this request: f1..fk
    text: str
    cite: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentRequest:
    idea: dict[str, Any]
    source_root: Path | None
    commit: str | None
    cached_facts: list[CachedFact]
    first_new_id: int
    allowed_domains: list[str]
    schema_hint: str
    attempt: int
    previous_issues: list[dict[str, str]]
    max_budget_usd: Decimal
    model: str | None = None


@dataclass(frozen=True, slots=True)
class AgentResponse:
    output: dict[str, Any]
    usage: Usage = field(default_factory=Usage)


class ResearchAgent(Protocol):
    async def run(self, request: AgentRequest) -> AgentResponse: ...


SCRIPT_HINT = """\
Write one JSON object: {"script": <manufacture.scenario/1>, "post": <manufacture.post/1>}, or
{"blocked": {"reason", "missing": [], "suggestion"}} when the research does not support the idea honestly.
Follow the idea first: its scenario_brief (what happens, in order), video_brief (pace, tone), design_notes,
constraints (duration, scenes, lines) and instructions.scenario. Facts come only from research.json (ids f1...).
Never type a number or output that comes from running a system: declare it in captures and reference it.
Every code line is {n, expect} and must match line n at the pinned commit. Terms marked must_explain need a note.
Human text is English. The post is {format, hook<=150, summary<=900, topic_hashtags[]}.
"""


@dataclass(frozen=True, slots=True)
class Revision:
    """A reviewer sent the script back: the previous script and what to change. `visit` counts the rounds."""

    visit: int
    previous_script: dict[str, Any]
    previous_post: dict[str, Any] | None
    comment: str


@dataclass(frozen=True, slots=True)
class ScriptRequest:
    idea: dict[str, Any]  # carries scenario_brief, video_brief, design_notes, palette, constraints, instructions
    research: dict[str, Any]
    source_root: Path | None
    schema_hint: str
    attempt: int
    previous_issues: list[dict[str, str]]
    revision: Revision | None
    max_budget_usd: Decimal
    model: str | None = None


class ScriptAgent(Protocol):
    async def run(self, request: ScriptRequest) -> AgentResponse: ...
