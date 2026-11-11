from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from claude_agent_sdk import ResultMessage

from mscenario.agent import SCHEMA_HINT, SCRIPT_HINT, AgentRequest, CachedFact, Revision, ScriptRequest
from mscenario.claude_agents import (
    ClaudeResearchAgent,
    ClaudeScriptAgent,
    extract_json,
    research_prompt,
    script_prompt,
)

IDEA = {
    "idea_ref": "idea:1:v1", "title": "T", "scenario_brief": "show the copy", "video_brief": "calm",
    "design_notes": "cold", "instructions": {"research": "prefer the docs", "scenario": "no jokes"},
    "constraints": {"duration_s": {"min": 25, "max": 40}}, "palette": {"ink": "#000000"}, "notes": "",
}  # fmt: skip


def result(text: str, cost: float = 0.12) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=2,
        session_id="s",
        total_cost_usd=cost,
        result=text,
        model_usage={
            "m": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 3, "cacheCreationInputTokens": 1}
        },
    )  # type: ignore[arg-type]


def fake_query(text: str, seen: list):  # type: ignore[no-untyped-def,type-arg]
    async def q(*, prompt, options):  # type: ignore[no-untyped-def]
        seen.append((prompt, options))
        yield result(text)

    return q


def test_extract_json_variants() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Here:\n```json\n{"a": {"b": 2}}\n```\nDone') == {"a": {"b": 2}}
    assert extract_json('noise {"a": 3} tail') == {"a": 3}
    assert extract_json("no json") == {} and extract_json("[1, 2]") == {} and extract_json("{broken") == {}


def request(**over) -> AgentRequest:  # type: ignore[no-untyped-def]
    base = dict(
        idea=IDEA, source_root=Path("/tree"), commit="a" * 40, cached_facts=[CachedFact("f1", "cached text", {})],
        first_new_id=2, allowed_domains=["github.com"], schema_hint=SCHEMA_HINT, attempt=0, previous_issues=[],
        max_budget_usd=Decimal("0.5"),
    )  # fmt: skip
    return AgentRequest(**{**base, **over})


def test_research_prompt_uses_idea_cache_and_issues_but_not_unrelated_fields() -> None:
    p = research_prompt(request(previous_issues=[{"rule": "cite", "message": "quote not found"}]))
    assert "show the copy" in p and "prefer the docs" in p and "no jokes" not in p and "palette" not in p
    assert "cached text" in p and "f2" in p and "quote not found" in p and "github.com" in p


def test_script_prompt_carries_revision_comment_and_previous_script() -> None:
    rev = Revision(2, {"scenes": ["old"]}, {"hook": "old hook"}, "shorten the hook")
    r = ScriptRequest(IDEA, {"facts": []}, None, SCRIPT_HINT, 0, [], rev, Decimal(1))
    p = script_prompt(r)
    assert (
        "no jokes" in p
        and "shorten the hook" in p
        and "old hook" in p
        and "round 2" in p
        and "prefer the docs" not in p
    )


async def test_research_agent_maps_result_usage_and_limits_tools() -> None:
    seen: list = []  # type: ignore[type-arg]
    resp = await ClaudeResearchAgent(fake_query('```json\n{"facts": []}\n```', seen)).run(request())
    assert resp.output == {"facts": []} and resp.usage.cost_usd == Decimal("0.12")
    assert resp.usage.tokens["m"] == {"input": 10, "output": 5, "cache_read": 3, "cache_write": 1}
    opts = seen[0][1]
    assert opts.allowed_tools == ["Read", "Grep", "Glob", "WebFetch"] and opts.max_budget_usd == 0.5
    assert "Bash" not in opts.allowed_tools and opts.cwd == "/tree"


async def test_script_agent_has_no_web_and_no_tools_without_a_tree() -> None:
    seen: list = []  # type: ignore[type-arg]
    r = ScriptRequest(IDEA, {}, None, SCRIPT_HINT, 0, [], None, Decimal(1), model="m1")
    resp = await ClaudeScriptAgent(fake_query('{"script": {}}', seen)).run(r)
    assert resp.output == {"script": {}} and seen[0][1].allowed_tools == [] and seen[0][1].model == "m1"


async def test_no_result_message_is_an_empty_answer() -> None:
    async def q(*, prompt, options):  # type: ignore[no-untyped-def]
        return
        yield

    resp = await ClaudeResearchAgent(q).run(request())
    assert resp.output == {} and resp.usage.cost_usd == 0
