from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import ScriptedAgent
from mscenario.cache import KnowledgeCache
from mscenario.db import transaction
from mscenario.service import (
    BudgetExceeded,
    ResearchInvalid,
    ResearchService,
    ResearchSettings,
    SourceNotAllowed,
)
from mscenario.sources import GitSourceProvider, normalize_repo

Sm = async_sessionmaker[AsyncSession]
FACT = {"id": "f1", "text": "The planner picks a sequential scan for a small table",
        "cite": {"file": "src/main.c", "line": 6, "quote": "sequential scan when the table is small"}}  # fmt: skip


def idea(repo: str, n: int = 1, **kw: Any) -> dict[str, Any]:
    base = {
        "id": n, "rev": 1, "idea_ref": f"idea:{n}:v1", "title": "Sequential scan beats index",
        "description": "Why the planner picks a sequential scan on a small table", "tags": ["planner"],
        "key_takeaway": "small tables are scanned", "demo_commands": ["EXPLAIN SELECT 1"],
        "environment": {"allowed_repos": [{"repo": repo, "refs": ["main"]}]},
        "source_refs": [{"kind": "repo", "repo": repo, "ref": "main"}],
    }  # fmt: skip
    return base | kw


def delta(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "format": "manufacture.research.delta/1",
        "feasibility": {"decision": "go", "reason": "the behaviour is in the source"},
        "facts": [FACT,
                  {"id": "f2", "text": "main calls plan_query", "cite": {"file": "src/main.c", "line": 3, "quote": "plan_query();"}},
                  {"id": "f3", "text": "plan_query calls choose_scan", "cite": {"file": "src/main.c", "line": 7, "quote": "choose_scan();"}}],
        "terms": [{"term": "seq scan", "explain": "reads every row in order", "must_explain": True}],
        "capture_needs": [{"name": "plan_text", "meaning": "EXPLAIN output", "how": "run EXPLAIN"}],
    }  # fmt: skip
    return copy.deepcopy(base | kw)


def service(sm: Sm, agent: ScriptedAgent, tmp_path: Path, **cfg: Any) -> ResearchService:
    return ResearchService(sm, GitSourceProvider(work_dir=tmp_path), agent, ResearchSettings(**cfg))


async def test_happy_path_assembles_a_document_and_fills_the_cache(sm: Sm, repo: str, tmp_path: Path) -> None:
    agent = ScriptedAgent(delta())
    out = await service(sm, agent, tmp_path).run(idea(repo), "step-1")
    assert out.status == "done" and out.attempts == 1
    doc = out.document
    assert doc["format"] == "manufacture.research/2" and len(doc["commit"]) == 40
    assert [f["origin"] for f in doc["facts"]] == ["new"] * 3
    assert doc["knowledge"] == {"cache_hits": 0, "new_facts": 3}
    assert agent.requests[0].cached_facts == [] and agent.requests[0].first_new_id == 1
    async with transaction(sm) as s:
        assert await KnowledgeCache(s).count(normalize_repo(repo)) == 3


async def test_second_idea_on_the_same_system_reuses_only_relevant_cached_facts(
    sm: Sm, repo: str, tmp_path: Path
) -> None:
    await service(sm, ScriptedAgent(delta()), tmp_path).run(idea(repo), "s1")
    cite_a = {"file": "src/main.c", "line": 7, "quote": "choose_scan();"}
    cite_b = {"file": "src/main.c", "line": 1, "quote": "int main(void)"}

    class Reuse(ScriptedAgent):
        async def run(self, request):  # type: ignore[no-untyped-def]
            n = len(request.cached_facts)
            self.outputs = [
                delta(
                    facts=[
                        {"id": f"f{n + 1}", "text": "choose_scan is called last", "cite": cite_a},
                        {"id": f"f{n + 2}", "text": "the program starts in main", "cite": cite_b},
                    ],
                    reused_facts=[f.id for f in request.cached_facts],
                )
            ]
            return await super().run(request)

    agent = Reuse()
    out = await service(sm, agent, tmp_path).run(idea(repo, 2, title="Sequential scan planner choice"), "s2")
    req = agent.requests[0]
    offered = {f.text for f in req.cached_facts}
    assert "The planner picks a sequential scan for a small table" in offered
    assert "main calls plan_query" not in offered  # not relevant to this idea: no tokens spent on it
    assert req.first_new_id == len(req.cached_facts) + 1
    assert out.status == "done" and out.document["knowledge"]["cache_hits"] == len(req.cached_facts)
    assert out.document["knowledge"]["new_facts"] == 2


async def test_wrong_quote_costs_one_retry_with_exact_errors(sm: Sm, repo: str, tmp_path: Path) -> None:
    broken = delta()
    broken["facts"][0]["cite"]["quote"] = "this text is not on the line"
    agent = ScriptedAgent(broken, delta())
    out = await service(sm, agent, tmp_path).run(idea(repo), "s1")
    assert out.attempts == 2 and out.status == "done"
    assert out.usage.cost_usd == Decimal("0.4")
    assert "quote not found" in agent.requests[1].previous_issues[0]["message"]
    assert agent.requests[0].previous_issues == []


async def test_still_invalid_after_retries_raises_and_stores_nothing(sm: Sm, repo: str, tmp_path: Path) -> None:
    broken = delta()
    broken["facts"][0]["cite"]["line"] = 999
    agent = ScriptedAgent(broken, broken, broken)
    with pytest.raises(ResearchInvalid) as exc:
        await service(sm, agent, tmp_path).run(idea(repo), "s1")
    assert "does not exist" in exc.value.issues[0]["message"]
    async with transaction(sm) as s:
        assert await KnowledgeCache(s).count(normalize_repo(repo)) == 0  # nothing unverified is remembered


async def test_blocked_stops_at_once_and_is_stored(sm: Sm, repo: str, tmp_path: Path) -> None:
    blocked = {"format": "manufacture.research.delta/1",
               "feasibility": {"decision": "blocked", "reason": "no such behaviour", "missing": ["code path"]}}  # fmt: skip
    agent = ScriptedAgent(blocked)
    svc = service(sm, agent, tmp_path)
    out = await svc.run(idea(repo), "s1")
    assert out.status == "blocked" and out.document["reason"] == "no such behaviour" and len(agent.requests) == 1
    again = await svc.run(idea(repo), "s1")  # a retried step returns the stored result and spends nothing
    assert again.status == "blocked" and len(agent.requests) == 1


async def test_retried_step_does_not_call_the_agent_again(sm: Sm, repo: str, tmp_path: Path) -> None:
    agent = ScriptedAgent(delta())
    svc = service(sm, agent, tmp_path)
    first = await svc.run(idea(repo), "same-key")
    again = await svc.run(idea(repo), "same-key")
    assert again.document == first.document and len(agent.requests) == 1


async def test_budget_stops_further_retries(sm: Sm, repo: str, tmp_path: Path) -> None:
    broken = delta()
    broken["facts"][0]["cite"]["quote"] = "wrong quote here"
    agent = ScriptedAgent(broken, delta(), cost="1.0")
    with pytest.raises(BudgetExceeded):
        await service(sm, agent, tmp_path, budget_usd=Decimal("1.05")).run(idea(repo), "s1")
    assert len(agent.requests) == 1


async def test_agent_cannot_reuse_or_reuse_ids_it_was_not_given(sm: Sm, repo: str, tmp_path: Path) -> None:
    bad = delta(reused_facts=["f9"])
    agent = ScriptedAgent(bad, delta())
    out = await service(sm, agent, tmp_path).run(idea(repo), "s1")
    assert out.attempts == 2 and "not one of the cached facts" in agent.requests[1].previous_issues[0]["message"]


async def test_repository_outside_the_allowlist_is_refused(sm: Sm, repo: str, tmp_path: Path) -> None:
    i = idea(repo, source_refs=[{"kind": "repo", "repo": "https://github.com/evil/repo", "ref": "main"}])
    with pytest.raises(SourceNotAllowed):
        await service(sm, ScriptedAgent(), tmp_path).run(i, "s1")


async def test_research_without_a_repository_uses_documentation_only(sm: Sm, tmp_path: Path) -> None:
    doc_fact = {
        "id": "f1",
        "text": "TLS 1.3 removes the RSA key exchange",
        "cite": {"url": "https://github.com/x/y", "quote": "removes RSA"},
    }
    facts = [doc_fact, {**doc_fact, "id": "f2", "cite": {"url": "https://github.com/x/y", "quote": "one round trip"}},
             {**doc_fact, "id": "f3", "cite": {"url": "https://github.com/x/y", "quote": "forward secrecy"}}]  # fmt: skip
    agent = ScriptedAgent(delta(facts=facts))
    i = idea("", source_refs=[], environment=None)
    out = await service(sm, agent, tmp_path).run(i, "s1")
    assert out.status == "done" and out.document["system"] is None and out.document["commit"] is None
    assert agent.requests[0].source_root is None
