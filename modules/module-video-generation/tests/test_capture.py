from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from helpers import FakeRunner, ScriptedPlanner, load
from mvgen.agent import BudgetExceeded
from mvgen.capture import CaptureBlocked, CaptureFailure, CaptureService, check_values, plan_issues

IMAGE = {"key": "postgres17", "version_expect": "17"}


def test_reference_plan_is_valid_for_the_reference_script() -> None:
    assert plan_issues(load("capture.plan.json"), load("script.en.json")) == []


def test_plan_issues_name_unknown_and_unused_commands() -> None:
    plan = copy.deepcopy(load("capture.plan.json"))
    plan["ops"] = [op for op in plan["ops"] if op.get("cmd") != "c-list-dbs"]
    plan["ops"].append({"op": "run", "cmd": "c-nope"})
    issues = plan_issues(plan, load("script.en.json"))
    assert any("c-nope" in i for i in issues)
    assert any("c-list-dbs" in i and "never run" in i for i in issues)


def test_plan_issues_require_why_equal_and_declared_sessions() -> None:
    plan = copy.deepcopy(load("capture.plan.json"))
    plan["ops"].append({"op": "value", "session": "ghost", "name": "x", "query": "select 1"})
    issues = plan_issues(plan, load("script.en.json"))
    assert any("ghost" in i for i in issues)
    assert any("why_equal" in i for i in issues)


def test_check_values() -> None:
    cap = {"values": {"a": {"value": "", "kind": "number", "raw": []}, "b": {"value": "x1", "kind": "number"},
                      "c": {"value": "ok", "kind": "text"}}}  # fmt: skip
    problems = check_values(cap)
    assert len(problems) == 2 and "a" in problems[0] and "b" in problems[1]
    assert check_values(load("capture.json")) == []


def service(sm, planner, runner, rounds: int = 2) -> CaptureService:  # type: ignore[no-untyped-def]
    return CaptureService(sm, planner, runner, fix_rounds=rounds)


async def test_records_capture_and_caches_it(sm) -> None:  # type: ignore[no-untyped-def]
    script, plan = load("script.en.json"), load("capture.plan.json")
    planner, runner = ScriptedPlanner(plan), FakeRunner()
    svc = service(sm, planner, runner)
    out = await svc.run(script, {}, {}, IMAGE, "r1", Decimal(1))
    assert out.rounds == 0 and not out.cached and out.usage.cost_usd == Decimal("0.2")
    again = await svc.run(script, {}, {}, IMAGE, "r2", Decimal(1))  # another run, same plan: no sandbox
    assert again.cached and runner.calls == 1


async def test_failed_run_costs_one_retry_with_the_log(sm) -> None:  # type: ignore[no-untyped-def]
    script, plan = load("script.en.json"), load("capture.plan.json")
    planner = ScriptedPlanner(plan)
    runner = FakeRunner(fail=[CaptureFailure("not_reproducible", "op 3 failed", "the log")])
    out = await service(sm, planner, runner).run(script, {}, {}, IMAGE, "r", Decimal(1))
    assert out.rounds == 1 and runner.calls == 2
    second = planner.requests[1]
    assert second.problems == ["op 3 failed"] and second.execution_log == "the log" and second.session_id == "sess-1"


async def test_version_mismatch_is_not_retried(sm) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(fail=[CaptureFailure("version_mismatch", "got 16")])
    with pytest.raises(CaptureBlocked) as e:
        await service(sm, ScriptedPlanner(load("capture.plan.json")), runner).run(
            load("script.en.json"), {}, {}, IMAGE, "r", Decimal(1)
        )
    assert e.value.code == "version_mismatch" and runner.calls == 1


async def test_gives_up_after_the_fix_rounds(sm) -> None:  # type: ignore[no-untyped-def]
    fails = [CaptureFailure("not_reproducible", f"boom {i}") for i in range(5)]
    with pytest.raises(CaptureBlocked) as e:
        await service(sm, ScriptedPlanner(load("capture.plan.json")), FakeRunner(fail=fails), rounds=1).run(
            load("script.en.json"), {}, {}, IMAGE, "r", Decimal(5)
        )
    assert e.value.code == "not_reproducible" and e.value.problems == ["boom 1"]


async def test_invalid_plan_never_reaches_the_sandbox(sm) -> None:  # type: ignore[no-untyped-def]
    bad = {"sessions": {"psql": {"kind": "psql"}}, "ops": [{"op": "run", "cmd": "c-nope"}]}
    runner = FakeRunner()
    out = await service(sm, ScriptedPlanner(bad, load("capture.plan.json")), runner).run(
        load("script.en.json"), {}, {}, IMAGE, "r", Decimal(1)
    )
    assert out.rounds == 1 and runner.calls == 1


async def test_budget_stops_the_planner(sm) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(fail=[CaptureFailure("not_reproducible", "x")] * 3)
    with pytest.raises(BudgetExceeded):
        await service(sm, ScriptedPlanner(load("capture.plan.json"), cost="0.6"), runner).run(
            load("script.en.json"), {}, {}, IMAGE, "r", Decimal("1")
        )


async def test_revision_reuses_capture_when_commands_are_unchanged(sm) -> None:  # type: ignore[no-untyped-def]
    script, plan = load("script.en.json"), load("capture.plan.json")
    planner, runner = ScriptedPlanner(plan), FakeRunner()
    svc = service(sm, planner, runner)
    first = await svc.run(script, {}, {}, IMAGE, "r1", Decimal(1))
    revised = copy.deepcopy(script)
    revised["meta"]["title"] = "another title"
    out = await svc.run(revised, {}, {}, IMAGE, "r2", Decimal(1), (first.plan, first.capture))
    assert out.cached and out.usage.cost_usd == 0 and len(planner.requests) == 1
