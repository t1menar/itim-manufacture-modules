from __future__ import annotations

from decimal import Decimal

from manufacture.testing import call_run_event, call_source, run_finished, run_started
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from midea.adapter import make_app, run_id_for
from midea.db import transaction
from midea.service import IdeaService, SchedulerPolicy
from test_service import queued, seed

Sm = async_sessionmaker[AsyncSession]


async def idea_status(sm: Sm, idea_id: int) -> tuple[str, Decimal]:
    async with transaction(sm) as s:
        i = await IdeaService(s).get_idea(idea_id)
        return i.status, Decimal(i.cost_spent_usd)


async def test_source_starts_one_run_per_queued_idea_with_the_idea_document(sm: Sm) -> None:
    async with transaction(sm) as s:
        svc = IdeaService(s)
        await seed(svc)
        a = await queued(svc, title="First idea", scenario_brief="show the copy", palette={"ink": "#112233"})
        b = await queued(svc, title="Second idea")
    app = make_app(lambda: transaction(sm), SchedulerPolicy(max_in_flight=1))
    res = await call_source(app)
    assert res.acked and len(res.runs) == 1  # the in-flight cap
    run = res.runs[0]
    doc = run["data"]["idea"]
    assert run["dedup_key"] == doc["idea_ref"] == f"idea:{a}:v1" and doc["palette"] == {"ink": "#112233"}
    assert doc["scenario_brief"] == "show the copy" and doc["environment"]["code"] == "postgres17"
    assert (await idea_status(sm, a))[0] == "dispatched" and (await idea_status(sm, b))[0] == "queued"
    assert (await call_source(app)).runs == []  # nothing free: the cap is reached


async def test_run_events_walk_the_idea_to_done_and_record_cost(sm: Sm) -> None:
    async with transaction(sm) as s:
        svc = IdeaService(s)
        await seed(svc)
        i = await queued(svc)
    app = make_app(lambda: transaction(sm), SchedulerPolicy())
    run = (await call_source(app)).runs[0]
    ref = run["data"]["idea"]["idea_ref"]
    assert run["labels"] == {"idea_ref": ref}
    labels = {"idea_ref": ref}
    assert await call_run_event(app, run_started(labels=labels))
    assert (await idea_status(sm, i))[0] == "in_production"
    assert await call_run_event(app, run_finished(labels=labels, cost_usd=1.25))
    assert await idea_status(sm, i) == ("done", Decimal("1.25"))
    assert await call_run_event(app, run_finished(status="failed", labels=labels))  # replay never moves back
    assert (await idea_status(sm, i))[0] == "done"


async def test_failed_run_marks_the_idea_failed_and_foreign_runs_are_ignored(sm: Sm) -> None:
    async with transaction(sm) as s:
        svc = IdeaService(s)
        await seed(svc)
        i = await queued(svc)
    app = make_app(lambda: transaction(sm), SchedulerPolicy())
    ref = (await call_source(app)).runs[0]["data"]["idea"]["idea_ref"]
    err = {"message": "script blocked"}
    assert await call_run_event(app, run_finished(status="failed", labels={"idea_ref": ref}, error=err))
    assert (await idea_status(sm, i))[0] == "failed"
    assert await call_run_event(app, run_started(labels={"idea_ref": "idea:999:v1"}))
    assert await call_run_event(app, run_started())
    assert run_id_for("idea:1:v1") == "src:idea:1:v1"
