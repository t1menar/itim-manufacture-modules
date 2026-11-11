"""Claude Agent SDK implementations of `ResearchAgent` and `ScriptAgent`.

The prompt carries only what the idea and the pinned source decide; limits live in the validators, so a
wrong answer costs one cheap retry with the exact issues (`previous_issues`). Research may read the pinned tree
and fetch allowed web pages; the script agent reads the tree only (the research is already done). Both run with
a USD budget and a turn cap, and never get shell or write tools.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

from mscenario.agent import AgentRequest, AgentResponse, ScriptRequest, Usage

QueryFn = Callable[..., AsyncIterator[Any]]

RESEARCH_SYSTEM = (
    "You verify and research one short technical video idea for an English tech channel. You read the pinned source "
    "tree (your working directory) and, only if the idea needs it, fetch pages from the allowed domains. You never "
    "invent facts: every fact carries a citation that a program will check against the source. Answer with one JSON "
    "object and nothing else."
)
SCRIPT_SYSTEM = (
    "You write the scenario of one short technical video from verified research. You follow the idea's briefs and "
    "constraints exactly. You never type numbers that come from running a system. Answer with one JSON object and "
    "nothing else."
)
JSON_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


def extract_json(text: str) -> dict[str, Any]:
    """The JSON object of an agent answer: bare, fenced, or the outermost braces. {} when there is none."""
    text = text.strip()
    for candidate in (text, *(m.group(1) for m in JSON_RE.finditer(text))):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            value = json.loads(text[start : end + 1])
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def usage_of(result: Any) -> Usage:
    cost = Decimal(str(getattr(result, "total_cost_usd", None) or 0))
    tokens: dict[str, dict[str, int]] = {}
    for model, mu in (getattr(result, "model_usage", None) or {}).items():
        data: dict[str, Any] = mu if isinstance(mu, dict) else vars(mu)
        get = data.get
        tokens[model] = {
            "input": int(get("inputTokens", 0) or 0), "output": int(get("outputTokens", 0) or 0),
            "cache_read": int(get("cacheReadInputTokens", 0) or 0),
            "cache_write": int(get("cacheCreationInputTokens", 0) or 0),
        }  # fmt: skip
    return Usage(cost, tokens)


def idea_section(idea: dict[str, Any], stage: str) -> str:
    """The idea fields that steer a stage; absent ones are left out."""
    ins = (idea.get("instructions") or {}).get(stage)
    keys = ("title", "description", "key_takeaway", "hook", "audience", "rubric", "demo_commands", "expected_result",
            "must_show", "must_avoid", "scenario_brief", "video_brief", "design_notes", "constraints")  # fmt: skip
    body = {k: idea[k] for k in keys if idea.get(k) not in (None, "", [], {})}
    text = "IDEA:\n" + json.dumps(body, ensure_ascii=False, indent=1)
    return text + (f"\n\nEXTRA INSTRUCTIONS FOR THIS STAGE (from the idea owner):\n{ins}" if ins else "")


def research_prompt(r: AgentRequest) -> str:
    parts = [idea_section(r.idea, "research")]
    parts.append(f"Pinned commit: {r.commit}" if r.commit else "No source tree is pinned for this idea.")
    if r.cached_facts:
        facts = [{"id": f.id, "text": f.text} for f in r.cached_facts]
        parts.append("CACHED FACTS (already verified, do not repeat; list ids you rely on in reused_facts):\n"
                     + json.dumps(facts, ensure_ascii=False))  # fmt: skip
    parts.append(f"New fact ids start at f{r.first_new_id}. Allowed web domains: {', '.join(r.allowed_domains)}.")
    parts.append(r.schema_hint)
    if r.previous_issues:
        parts.append("YOUR PREVIOUS ANSWER HAD THESE PROBLEMS, fix exactly these:\n"
                     + json.dumps(r.previous_issues, ensure_ascii=False, indent=1))  # fmt: skip
    return "\n\n".join(parts)


def _previous_post(post: dict[str, Any] | None) -> str:
    return "\n\nPREVIOUS POST:\n" + json.dumps(post, ensure_ascii=False) if post else ""


def script_prompt(r: ScriptRequest) -> str:
    parts = [
        idea_section(r.idea, "scenario"),
        "VERIFIED RESEARCH (research.json):\n" + json.dumps(r.research, ensure_ascii=False),
    ]
    if r.revision:
        parts.append(
            f"The reviewer sent the script back (round {r.revision.visit}). Change only what the comment asks, keep "
            f"everything else.\nREVIEWER COMMENT:\n{r.revision.comment}\n\nPREVIOUS SCRIPT:\n"
            + json.dumps(r.revision.previous_script, ensure_ascii=False)
            + _previous_post(r.revision.previous_post)
        )  # fmt: skip
    parts.append(r.schema_hint)
    if r.previous_issues:
        parts.append("YOUR PREVIOUS ANSWER HAD THESE PROBLEMS, fix exactly these:\n"
                     + json.dumps(r.previous_issues, ensure_ascii=False, indent=1))  # fmt: skip
    return "\n\n".join(parts)


async def run_query(
    query: QueryFn, prompt: str, system: str, *, cwd: str | None, tools: list[str], budget: Decimal,
    model: str | None, max_turns: int,
) -> AgentResponse:  # fmt: skip
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage  # noqa: PLC0415

    options = ClaudeAgentOptions(
        system_prompt=system, cwd=cwd, allowed_tools=tools, tools=tools, permission_mode="dontAsk",
        max_turns=max_turns, max_budget_usd=float(budget), model=model, setting_sources=[],
    )  # fmt: skip
    result: Any = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result = message
    if result is None:
        return AgentResponse({}, Usage())
    return AgentResponse(extract_json(result.result or ""), usage_of(result))


class ClaudeResearchAgent:
    def __init__(self, query: QueryFn | None = None, max_turns: int = 30) -> None:
        self._query, self.max_turns = query, max_turns

    async def run(self, request: AgentRequest) -> AgentResponse:
        query = self._query or _default_query()
        tools = ["Read", "Grep", "Glob", "WebFetch"] if request.source_root else ["WebFetch"]
        return await run_query(
            query, research_prompt(request), RESEARCH_SYSTEM,
            cwd=str(request.source_root) if request.source_root else None, tools=tools,
            budget=request.max_budget_usd, model=request.model, max_turns=self.max_turns,
        )  # fmt: skip


class ClaudeScriptAgent:
    def __init__(self, query: QueryFn | None = None, max_turns: int = 12) -> None:
        self._query, self.max_turns = query, max_turns

    async def run(self, request: ScriptRequest) -> AgentResponse:
        query = self._query or _default_query()
        return await run_query(
            query, script_prompt(request), SCRIPT_SYSTEM,
            cwd=str(request.source_root) if request.source_root else None,
            tools=["Read", "Grep", "Glob"] if request.source_root else [],
            budget=request.max_budget_usd, model=request.model, max_turns=self.max_turns,
        )  # fmt: skip


def _default_query() -> QueryFn:
    from claude_agent_sdk import query  # noqa: PLC0415

    return query
