from __future__ import annotations

from decimal import Decimal

from manufacture.testing import call_source, call_step
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


async def test_status_step_walks_the_idea_to_done_and_records_cost(sm: Sm) -> None:
    async with transaction(sm) as s:
        svc = IdeaService(s)
        await seed(svc)
        i = await queued(svc)
    app = make_app(lambda: transaction(sm), SchedulerPolicy())
    ref = (await call_source(app)).runs[0]["data"]["idea"]["idea_ref"]
    res = await call_step(app, {"idea_ref": ref, "status": "running"})
    assert res.type == "step.succeeded" and res.payload["output"]["idea_status"] == "in_production"
    done = await call_step(app, {"idea_ref": ref, "status": "succeeded", "cost_usd": "1.25"})
    assert done.payload["output"]["idea_status"] == "done" and await idea_status(sm, i) == ("done", Decimal("1.25"))
    again = await call_step(app, {"idea_ref": ref, "status": "failed", "error": "late"})  # replay never moves back
    assert again.payload["output"]["idea_status"] == "done"


async def test_failed_run_marks_the_idea_failed_and_unknown_runs_are_ignored(sm: Sm) -> None:
    async with transaction(sm) as s:
        svc = IdeaService(s)
        await seed(svc)
        i = await queued(svc)
    app = make_app(lambda: transaction(sm), SchedulerPolicy())
    ref = (await call_source(app)).runs[0]["data"]["idea"]["idea_ref"]
    res = await call_step(app, {"idea_ref": ref, "status": "failed", "error": "script blocked"})
    assert res.payload["output"]["idea_status"] == "failed" and (await idea_status(sm, i))[0] == "failed"
    other = await call_step(app, {"idea_ref": "idea:999:v1", "status": "running"})
    assert other.payload["output"]["idea_status"] is None
    bad = await call_step(app, {"idea_ref": "nope", "status": "running"})
    assert bad.payload["class"] == "fatal" and run_id_for("idea:1:v1") == "src:idea:1:v1"
