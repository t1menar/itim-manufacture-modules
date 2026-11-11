from __future__ import annotations

from pathlib import Path
from typing import Any

from manufacture.testing import call_step
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import ScriptedAgent
from mscenario.adapter import make_app
from mscenario.sources import GitSourceProvider
from test_pipeline import build, delta_from_reference, idea, ref_repo, scripted_script  # noqa: F401

Sm = async_sessionmaker[AsyncSession]


async def app_for(sm: Sm, repo: str, tmp_path: Path, research: list[dict[str, Any]], script: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    commit = (await GitSourceProvider(work_dir=tmp_path).checkout(repo, "main"))[0].commit
    svc = build(sm, tmp_path, ScriptedAgent(*[x or delta_from_reference() for x in research]),
                ScriptedAgent(*[x or scripted_script(commit) for x in script]))  # fmt: skip

    async def provider():  # type: ignore[no-untyped-def]
        return svc

    return make_app(provider), commit


async def test_step_succeeds_with_research_script_and_post(sm: Sm, ref_repo: str, tmp_path: Path) -> None:  # noqa: F811
    app, commit = await app_for(sm, ref_repo, tmp_path, [{}], [{}])
    res = await call_step(app, {"idea": idea(ref_repo)})
    assert res.type == "step.succeeded", res.payload
    out = res.payload["output"]
    assert out["research"]["commit"] == commit and out["post"]["format"] == "manufacture.post/1"
    assert float(out["cost_usd"]) > 0 and out["attempts"] >= 2


async def test_blocked_idea_needs_attention(sm: Sm, ref_repo: str, tmp_path: Path) -> None:  # noqa: F811
    blocked = {"format": "manufacture.research.delta/1",
               "feasibility": {"decision": "blocked", "reason": "needs a cluster", "missing": ["cluster"], "suggestion": "use one node"}}  # fmt: skip
    app, _ = await app_for(sm, ref_repo, tmp_path, [blocked], [])
    res = await call_step(app, {"idea": idea(ref_repo)})
    assert (
        res.type == "step.failed" and res.payload["class"] == "attention" and res.payload["code"] == "scenario_blocked"
    )
    assert "needs a cluster" in res.payload["message"]


async def test_disallowed_source_is_fatal(sm: Sm, ref_repo: str, tmp_path: Path) -> None:  # noqa: F811
    app, _ = await app_for(sm, ref_repo, tmp_path, [{}], [{}])
    bad = idea(ref_repo)
    bad["source_refs"] = [{"kind": "repo", "repo": "file:///elsewhere", "ref": "main"}]
    res = await call_step(app, {"idea": bad})
    assert res.type == "step.failed" and res.payload["class"] == "fatal" and res.payload["code"] == "source_not_allowed"


async def test_invalid_input_is_fatal_input_invalid(sm: Sm, ref_repo: str, tmp_path: Path) -> None:  # noqa: F811
    app, _ = await app_for(sm, ref_repo, tmp_path, [], [])
    res = await call_step(
        app, {"idea": idea(ref_repo), "revision": {"round": 0, "comment": "x", "previous_script": {}}}
    )
    assert res.type == "step.failed" and res.payload["code"] == "input_invalid"
