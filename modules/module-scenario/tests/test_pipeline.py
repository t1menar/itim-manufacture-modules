from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from helpers import ScriptedAgent
from mscenario.agent import Revision
from mscenario.pipeline import ScenarioService
from mscenario.script import ScriptService
from mscenario.service import ResearchService, ResearchSettings
from mscenario.sources import GitSourceProvider

REF = Path(__file__).parent / "reference"
Sm = async_sessionmaker[AsyncSession]
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def load(name: str) -> Any:
    return json.loads((REF / name).read_text())


@pytest.fixture
def ref_repo(tmp_path: Path) -> str:
    """The reference sources as a real git repository."""
    root = tmp_path / "pg"
    shutil.copytree(REF / "sources", root)
    for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-q", "-m", "ref"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, env={**os.environ, **ENV})
    return f"file://{root}"


def delta_from_reference() -> dict[str, Any]:
    r = load("research.json")
    return {
        "format": "manufacture.research.delta/1",
        "feasibility": {"decision": "go", "reason": "the behaviour is in the source"},
        "facts": r["facts"], "terms": r["terms"], "capture_needs": r["capture_needs"],
        "call_path": r["call_path"], "misconceptions": r["misconceptions"],
        "viewer_questions": r["viewer_questions"],
    }  # fmt: skip


def idea(repo: str) -> dict[str, Any]:
    return {
        "id": 1, "rev": 1, "idea_ref": "idea:1:v1", "title": "CREATE DATABASE",
        "description": "What the server does on CREATE DATABASE", "tags": [],
        "environment": {"allowed_repos": [{"repo": repo, "refs": ["main"]}]},
        "source_refs": [{"kind": "repo", "repo": repo, "ref": "main"}],
        "constraints": {"duration_s": {"min": 60, "max": 200}, "allowed_domains": ["postgresql.org", "stackoverflow.com"]},
    }  # fmt: skip


def scripted_script(commit: str) -> dict[str, Any]:
    script = load("script.en.json")
    script["meta"]["system"]["commit"] = commit
    return {"script": script, "post": load("post.en.json")}


def build(sm: Sm, tmp_path: Path, research_agent: ScriptedAgent, script_agent: ScriptedAgent) -> ScenarioService:
    cfg = ResearchSettings(allowed_domains=("postgresql.org", "stackoverflow.com", "github.com"))
    research = ResearchService(sm, GitSourceProvider(work_dir=tmp_path), research_agent, cfg)
    return ScenarioService(research, ScriptService(sm, script_agent, cfg))


async def test_research_then_script_on_one_pinned_tree(sm: Sm, ref_repo: str, tmp_path: Path) -> None:
    probe = await GitSourceProvider(work_dir=tmp_path).checkout(ref_repo, "main")
    commit = probe[0].commit
    # the reference research carries its own commit; the real one comes from the pinned checkout
    ra, sa = ScriptedAgent(delta_from_reference()), ScriptedAgent(scripted_script(commit))
    out = await build(sm, tmp_path, ra, sa).run(idea(ref_repo), "step-1")
    assert out.status == "done", out.document
    assert out.document["research"]["commit"] == commit
    assert out.document["script"]["meta"]["system"]["commit"] == commit
    assert sa.requests[0].research["commit"] == commit and sa.requests[0].source_root is not None


async def test_a_review_round_reuses_the_research_and_rewrites_only_the_script(
    sm: Sm, ref_repo: str, tmp_path: Path
) -> None:
    commit = (await GitSourceProvider(work_dir=tmp_path).checkout(ref_repo, "main"))[0].commit
    first = scripted_script(commit)
    ra = ScriptedAgent(delta_from_reference())
    sa = ScriptedAgent(copy.deepcopy(first))
    svc = build(sm, tmp_path, ra, sa)
    await svc.run(idea(ref_repo), "visit-1")
    second = copy.deepcopy(first)
    second["post"]["hook"] = "A sharper hook for the same story"
    sa.outputs.append(second)
    rev = Revision(2, first["script"], first["post"], "Make the hook sharper")
    out = await svc.run(idea(ref_repo), "visit-2", rev)
    assert out.status == "done" and out.document["post"]["hook"].startswith("A sharper")
    assert len(ra.requests) == 1  # research agent was not called again
    assert sa.requests[1].revision is not None and sa.requests[1].revision.comment == "Make the hook sharper"


async def test_a_blocked_research_never_reaches_the_script_phase(sm: Sm, ref_repo: str, tmp_path: Path) -> None:
    blocked = {
        "format": "manufacture.research.delta/1",
        "feasibility": {"decision": "blocked", "reason": "no such path"},
    }
    ra, sa = ScriptedAgent(blocked), ScriptedAgent()
    out = await build(sm, tmp_path, ra, sa).run(idea(ref_repo), "s1")
    assert out.status == "blocked" and out.document["phase"] == "research" and sa.requests == []
