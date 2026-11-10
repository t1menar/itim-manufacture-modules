from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import ScriptedAgent
from mscenario.agent import Revision
from mscenario.script import ScriptService
from mscenario.service import BudgetExceeded, ResearchInvalid, ResearchSettings
from mscenario.sources import SourceTree

REF = Path(__file__).parent / "reference"
Sm = async_sessionmaker[AsyncSession]


def load(name: str) -> Any:
    return json.loads((REF / name).read_text())


def idea(**constraints: Any) -> dict[str, Any]:
    return {
        "id": 1, "rev": 1, "idea_ref": "idea:1:v1", "title": "CREATE DATABASE",
        "scenario_brief": "Walk through what the server does.",
        "constraints": {"duration_s": {"min": 60, "max": 200}, **constraints},
    }  # fmt: skip


def good() -> dict[str, Any]:
    return {"script": load("script.en.json"), "post": load("post.en.json")}


def service(sm: Sm, agent: ScriptedAgent, **cfg: Any) -> ScriptService:
    return ScriptService(sm, agent, ResearchSettings(**cfg))


@pytest.fixture
def tree() -> SourceTree:
    return SourceTree(REF / "sources")


async def run(svc: ScriptService, tree: SourceTree, key: str = "k1", **kw: Any) -> Any:
    return await svc.run(kw.pop("idea", idea()), load("research.json"), key, tree, kw.pop("revision", None))


async def test_a_valid_scenario_is_accepted_and_stored(sm: Sm, tree: SourceTree) -> None:
    agent = ScriptedAgent(good())
    out = await run(service(sm, agent), tree)
    assert out.status == "done" and out.attempts == 1
    assert out.document["script"]["format"] == "manufacture.scenario/1" and "hook" in out.document["post"]
    again = await run(service(sm, ScriptedAgent()), tree)  # a retried step: stored result, no agent call
    assert again.document == out.document


async def test_the_idea_supplies_the_limits(sm: Sm, tree: SourceTree) -> None:
    short = idea(duration_s={"min": 20, "max": 40})  # the reference runs about 160 s
    agent = ScriptedAgent(good(), good(), good())
    with pytest.raises(ResearchInvalid) as exc:
        await run(service(sm, agent), tree, idea=short)
    assert any("allowed 20 to 40" in i["message"] for i in exc.value.issues)
    assert len(agent.requests) == 3
    assert agent.requests[0].idea["constraints"]["duration_s"] == {"min": 20, "max": 40}


async def test_a_typed_number_costs_one_retry_with_the_exact_error(sm: Sm, tree: SourceTree) -> None:
    bad = good()
    bad["script"]["scenes"][0]["captions"][0]["lines"][0] = "It takes 4242 steps"
    agent = ScriptedAgent(bad, good())
    out = await run(service(sm, agent), tree)
    assert out.attempts == 2
    assert [i["rule"] for i in agent.requests[1].previous_issues] == ["numbers_sourced"]
    assert agent.requests[0].previous_issues == []


async def test_a_wrong_code_line_is_caught_against_the_pinned_commit(sm: Sm, tree: SourceTree) -> None:
    bad = json.loads(json.dumps(good()).replace('"expect": "GetNewOidWithIndex"', '"expect": "NotOnThatLine"', 1))
    agent = ScriptedAgent(bad, good())
    out = await run(service(sm, agent), tree)
    assert out.attempts == 2
    assert [i["rule"] for i in agent.requests[1].previous_issues] == ["expect_match"]
    assert "NotOnThatLine" in agent.requests[1].previous_issues[0]["message"]


async def test_research_commit_must_match_the_scenario(sm: Sm, tree: SourceTree) -> None:
    agent = ScriptedAgent(good(), good(), good())
    research = load("research.json")
    research["commit"] = "0" * 40
    with pytest.raises(ResearchInvalid) as exc:
        await service(sm, agent).run(idea(), research, "k1", tree)
    assert any("research commit" in i["message"] for i in exc.value.issues)


async def test_blocked_stops_at_once_and_is_stored(sm: Sm, tree: SourceTree) -> None:
    agent = ScriptedAgent({"blocked": {"reason": "no value can be captured", "missing": ["oid"]}})
    svc = service(sm, agent)
    out = await run(svc, tree)
    assert out.status == "blocked" and out.document["reason"] == "no value can be captured" and len(agent.requests) == 1
    assert (await run(svc, tree)).status == "blocked" and len(agent.requests) == 1


async def test_the_output_envelope_is_checked(sm: Sm, tree: SourceTree) -> None:
    agent = ScriptedAgent({"script": {}}, good())
    out = await run(service(sm, agent), tree)
    assert out.attempts == 2 and "post" in agent.requests[1].previous_issues[0]["message"]


async def test_revision_gets_the_comment_and_must_change_something(sm: Sm, tree: SourceTree) -> None:
    first = good()
    rev = Revision(visit=2, previous_script=first["script"], previous_post=first["post"], comment="Hook is too slow")
    changed = copy.deepcopy(first)
    changed["post"]["hook"] = "What does CREATE DATABASE really copy?"
    agent = ScriptedAgent(copy.deepcopy(first), changed)
    out = await run(service(sm, agent), tree, key="k2", revision=rev)
    assert out.attempts == 2 and out.document["post"]["hook"].startswith("What does")
    assert agent.requests[0].revision and agent.requests[0].revision.comment == "Hook is too slow"
    assert "nothing changed" in agent.requests[1].previous_issues[0]["message"]


async def test_budget_stops_retries(sm: Sm, tree: SourceTree) -> None:
    bad = good()
    bad["script"]["scenes"][0]["captions"][0]["lines"][0] = "It takes 4242 steps"
    agent = ScriptedAgent(bad, good(), cost="1.0")
    from decimal import Decimal

    with pytest.raises(BudgetExceeded):
        await run(service(sm, agent, budget_usd=Decimal("1.05")), tree)
