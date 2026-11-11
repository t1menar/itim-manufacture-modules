from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from claude_agent_sdk import ResultMessage
from manufacture.testing import call_step

from helpers import FakeRunner, ScriptedPlanner, Trees, load
from mvgen.adapter import make_app
from mvgen.capture import CaptureFailure, CaptureService, PlanRequest
from mvgen.claude_planner import ClaudeCapturePlanner, extract_json, plan_prompt
from mvgen.service import GenerationService
from mvgen.store import LocalStore
from mvgen.trees import DirTree, GitTrees, TreeError
from test_service import FONTS, idea, needs_ffmpeg, scenario


def app_for(sm, tmp_path: Path, runner: FakeRunner | None = None, **kw):  # type: ignore[no-untyped-def]
    captures = CaptureService(sm, ScriptedPlanner(load("capture.plan.json")), runner or FakeRunner())
    svc = GenerationService(sm, captures, Trees(), LocalStore(tmp_path / "store"), fonts_dir=FONTS, **kw)

    async def provider() -> GenerationService:
        return svc

    return make_app(provider)


async def test_failed_check_is_fatal(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    app = app_for(sm, tmp_path)
    res = await call_step(
        app, {"idea": idea(constraints={"duration_s": {"min": 20, "max": 45}}), "scenario": scenario()}
    )
    assert res.type == "step.failed" and res.payload["class"] == "fatal" and res.payload["code"] == "duration"


async def test_unreproducible_capture_needs_attention(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(fail=[CaptureFailure("version_mismatch", "got 16")])
    res = await call_step(app_for(sm, tmp_path, runner), {"idea": idea(), "scenario": scenario()})
    assert res.payload["class"] == "attention" and res.payload["code"] == "version_mismatch"


@needs_ffmpeg
async def test_step_output_on_success(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    app = app_for(sm, tmp_path, limit_frames=60)
    res = await call_step(app, {"idea": idea(), "scenario": scenario()}, timeout_s=240)
    assert res.type == "step.succeeded", res.payload
    assert res.payload["output"]["variants"][0]["video"]["ref"].startswith("file://")


def planner_result(text: str) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="sess-9",
        total_cost_usd=0.05,
        result=text,
    )  # type: ignore[arg-type]


def test_planner_prompt_first_and_fix_round() -> None:
    script = load("script.en.json")
    first = plan_prompt(
        PlanRequest(script, {"capture_needs": [{"name": "oid_shop"}]}, {"must_show": ["oid"]}, {"key": "postgres17"})
    )
    assert "c-list-dbs" in first and "oid_shop" in first and "must_show" in first and "why_equal" in first
    fix = plan_prompt(
        PlanRequest(script, {}, {}, {}, attempt=1, problems=["op 3 failed"], execution_log="LOG", session_id="s")
    )
    assert "op 3 failed" in fix and "LOG" in fix and "c-list-dbs" not in fix  # the session already has the script


async def test_planner_resumes_the_session_on_a_fix_round_and_has_no_tools() -> None:
    seen: list[Any] = []

    async def q(*, prompt, options):  # type: ignore[no-untyped-def]
        seen.append(options)
        yield planner_result('{"sessions": {}, "ops": []}')

    planner = ClaudeCapturePlanner(q)
    script = load("script.en.json")
    first = await planner.plan(PlanRequest(script, {}, {}, {"key": "postgres17"}, max_budget_usd=Decimal("0.3")))
    assert (
        first.session_id == "sess-9" and first.plan["image"] == "postgres17" and first.usage.cost_usd == Decimal("0.05")
    )
    await planner.plan(PlanRequest(script, {}, {}, {}, attempt=1, problems=["x"], session_id="sess-9"))
    assert seen[0].resume is None and seen[1].resume == "sess-9" and seen[0].allowed_tools == []
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1} and extract_json("nope") == {}


def test_dir_tree_is_confined_to_its_root(tmp_path: Path) -> None:
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "a.c").write_text("one\ntwo\n")
    (tmp_path / "secret.txt").write_text("x")
    tree = DirTree(tmp_path / "t")
    assert tree.exists("a.c") and tree.line("a.c", 2) == "two" and tree.line("a.c", 9) is None
    assert not tree.exists("../secret.txt") and tree.line("../secret.txt", 1) is None


async def test_git_trees_fetch_one_commit_and_reuse_it(tmp_path: Path) -> None:
    import os
    import subprocess

    repo = tmp_path / "r"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    (repo / "f.c").write_text("line1\nline2\n")
    for cmd in (
        ["init", "-q", "-b", "main"],
        ["add", "."],
        ["commit", "-q", "-m", "x"],
        ["config", "uploadpack.allowAnySHA1InWant", "true"],
    ):
        subprocess.run(["git", *cmd], cwd=repo, check=True, env=env)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    trees = GitTrees(tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    tree = await trees.open(f"file://{repo}", commit)
    assert tree.line("f.c", 2) == "line2"
    (repo / "f.c").write_text("changed\n")  # the pinned commit does not move
    assert (await trees.open(f"file://{repo}", commit)).line("f.c", 2) == "line2"
    try:
        await trees.open("file:///nope", "abc")
    except TreeError as exc:
        assert "full commit id" in str(exc)
