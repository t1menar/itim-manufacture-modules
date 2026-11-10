from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from midea import schemas
from midea.service import Conflict, IdeaService, NotFound, NotReady, SchedulerPolicy
from midea.status import IdeaStatus, TransitionError

DESC = "Explain why a sequential scan can beat an index scan on a small table with a live demo"


async def seed(svc: IdeaService) -> None:
    await svc.upsert_environment(schemas.EnvironmentIn(code="postgres17", title="Postgres 17"))
    await svc.upsert_rubric(schemas.RubricIn(code="race", title="Race"))


def idea_in(**kw: object) -> schemas.IdeaIn:
    base: dict[str, object] = {
        "title": "Seq scan beats index",
        "description": DESC,
        "key_takeaway": "Small tables are faster to scan than to index",
        "rubric_code": "race",
        "environment_code": "postgres17",
    }
    return schemas.IdeaIn(**(base | kw))  # type: ignore[arg-type]


async def queued(svc: IdeaService, **kw: object) -> int:
    idea = await svc.create_idea(idea_in(**kw))
    await svc.set_status(idea.id, IdeaStatus.QUEUED)
    return idea.id


async def test_create_snapshots_revision_one(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    idea = await svc.create_idea(idea_in())
    doc = await svc.revision_document(idea.id, 1)
    assert doc["idea_ref"] == f"idea:{idea.id}:v1"
    assert doc["rubric"]["code"] == "race" and doc["environment"]["code"] == "postgres17"


async def test_update_bumps_revision_only_for_content(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    idea = await svc.create_idea(idea_in())
    await svc.update_idea(idea.id, schemas.IdeaPatch(priority=5))
    assert idea.rev == 1
    await svc.update_idea(idea.id, schemas.IdeaPatch(hook="Which is faster?"))
    assert idea.rev == 2
    assert (await svc.revision_document(idea.id, 1))["hook"] is None
    assert (await svc.revision_document(idea.id, 2))["hook"] == "Which is faster?"


async def test_queueing_requires_a_ready_idea(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    idea = await svc.create_idea(schemas.IdeaIn(title="x", description="too short"))
    with pytest.raises(NotReady) as exc:
        await svc.set_status(idea.id, IdeaStatus.QUEUED)
    assert len(exc.value.issues) == 4


async def test_invalid_transition_is_rejected(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    idea = await svc.create_idea(idea_in())
    with pytest.raises(TransitionError):
        await svc.set_status(idea.id, IdeaStatus.DONE)


async def test_unknown_references_are_not_found(session: AsyncSession) -> None:
    svc = IdeaService(session)
    with pytest.raises(NotFound):
        await svc.create_idea(idea_in(rubric_code="nope"))


async def test_scheduler_orders_by_priority_then_playlist_position(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    await svc.create_playlist(schemas.PlaylistIn(code="sql_basics", title="SQL basics"))
    a = await queued(svc, title="a")
    b = await queued(svc, title="b")
    c = await queued(svc, title="c", priority=10)
    await svc.add_to_playlist("sql_basics", b, position=0)
    await svc.add_to_playlist("sql_basics", a, position=1)
    picked = await svc.pick_next(SchedulerPolicy(max_in_flight=10), limit=3)
    assert [i.id for i in picked] == [c, b, a]


async def test_scheduler_caps_in_flight_and_interval_and_pause(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    a, b = await queued(svc, title="a"), await queued(svc, title="b")
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    assert await svc.pick_next(SchedulerPolicy(paused=True)) == []
    await svc.dispatch(a, "run-a", now=now)
    assert await svc.pick_next(SchedulerPolicy(max_in_flight=1), now=now) == []
    assert await svc.pick_next(SchedulerPolicy(max_in_flight=5, min_interval_s=600), now=now) == []
    later = now + dt.timedelta(seconds=601)
    assert [i.id for i in await svc.pick_next(SchedulerPolicy(max_in_flight=5, min_interval_s=600), now=later)] == [b]


async def test_scheduler_skips_inactive_playlists_and_environments(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    await svc.create_playlist(schemas.PlaylistIn(code="paused_list", title="Paused", status="archived"))
    a = await queued(svc, title="a")
    await svc.add_to_playlist("paused_list", a)
    assert await svc.pick_next(SchedulerPolicy(max_in_flight=5)) == []
    await svc.create_playlist(schemas.PlaylistIn(code="live", title="Live"))
    await svc.add_to_playlist("live", a)  # in one active playlist is enough
    assert [i.id for i in await svc.pick_next(SchedulerPolicy(max_in_flight=5))] == [a]
    await svc.upsert_environment(schemas.EnvironmentIn(code="postgres17", title="Postgres 17", active=False))
    assert await svc.pick_next(SchedulerPolicy(max_in_flight=5)) == []


async def test_run_events_are_idempotent_and_monotonic(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    a = await queued(svc)
    await svc.dispatch(a, "run-1")
    assert await svc.dispatch(a, "run-1")  # replay does not fail
    running = schemas.RunEvent(run_id="run-1", status="running")
    done = schemas.RunEvent(run_id="run-1", status="succeeded", cost_usd=Decimal("2.5"))
    idea = await svc.apply_run_event(running)
    assert idea and idea.status == "in_production"
    await svc.apply_run_event(done)
    await svc.apply_run_event(done)  # replay
    await svc.apply_run_event(running)  # late, reordered
    idea = await svc.get_idea(a)
    assert idea.status == "done" and idea.cost_spent_usd == Decimal("2.5")
    assert await svc.apply_run_event(schemas.RunEvent(run_id="other", status="failed")) is None


async def test_failed_run_can_be_requeued_and_costs_add_up(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    a = await queued(svc)
    await svc.dispatch(a, "r1")
    await svc.apply_run_event(schemas.RunEvent(run_id="r1", status="failed", cost_usd=Decimal("1"), error="boom"))
    idea = await svc.get_idea(a)
    assert idea.status == "failed" and idea.last_error == "boom"
    await svc.set_status(a, IdeaStatus.QUEUED)
    assert idea.last_error is None
    await svc.dispatch(a, "r2")
    await svc.apply_run_event(schemas.RunEvent(run_id="r2", status="succeeded", cost_usd=Decimal("2")))
    assert (await svc.get_idea(a)).cost_spent_usd == Decimal("3")


async def test_in_production_idea_cannot_be_edited(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    a = await queued(svc)
    await svc.dispatch(a, "r1")
    with pytest.raises(Conflict):
        await svc.update_idea(a, schemas.IdeaPatch(title="new"))


async def test_stale_dispatch_is_released(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    a = await queued(svc)
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    await svc.dispatch(a, "r1", now=t0)
    assert await svc.release_stale(dt.timedelta(minutes=30), now=t0 + dt.timedelta(minutes=10)) == []
    assert await svc.release_stale(dt.timedelta(minutes=30), now=t0 + dt.timedelta(hours=1)) == [a]
    assert (await svc.get_idea(a)).status == "queued"


async def test_stats_per_1000_views_by_rubric(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    await svc.upsert_rubric(schemas.RubricIn(code="myth", title="Myth"))
    a = await queued(svc, rubric_code="race")
    b = await queued(svc, rubric_code="myth")
    for i, run in ((a, "ra"), (b, "rb")):
        await svc.dispatch(i, run)
        await svc.apply_run_event(schemas.RunEvent(run_id=run, status="succeeded", cost_usd=Decimal(1)))
    await svc.add_outcome(a, schemas.OutcomeIn(views=1000, saves=30, follows=4))
    await svc.add_outcome(a, schemas.OutcomeIn(views=2000, saves=50, follows=8))  # latest wins
    await svc.add_outcome(b, schemas.OutcomeIn(views=500, saves=5, follows=1))
    stats = {s.key: s for s in await svc.stats("rubric")}
    assert stats["race"].saves_per_1000 == 25.0 and stats["race"].follows_per_1000 == 4.0
    assert stats["myth"].saves_per_1000 == 10.0 and stats["race"].cost_usd == Decimal(1)


async def test_outcome_requires_published_idea(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    idea = await svc.create_idea(idea_in())
    with pytest.raises(Conflict):
        await svc.add_outcome(idea.id, schemas.OutcomeIn(views=1))


async def test_reorder_playlist(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    pl = await svc.create_playlist(schemas.PlaylistIn(code="plist", title="P"))
    ids = [(await svc.create_idea(idea_in(title=t))).id for t in "abc"]
    for i in ids:
        await svc.add_to_playlist("plist", i)
    await svc.reorder_playlist("plist", ids[::-1])
    assert await svc.playlist_idea_ids(pl.id) == ids[::-1]
    with pytest.raises(Conflict):
        await svc.reorder_playlist("plist", ids[:2])


async def test_brief_design_and_instructions_travel_in_the_document(session: AsyncSession) -> None:
    svc = IdeaService(session)
    await seed(svc)
    idea = await svc.create_idea(
        idea_in(
            scenario_brief="Hook with a question, race the two plans, reveal the timings, end on the rule of thumb.",
            video_brief="Fast, calm, no jokes. Reels, loopable ending.",
            design_notes="Dark terminal, one accent colour, big numbers.",
            palette={"win_accent": "#FF8800", "accent_top": "#00AAFF"},
            instructions={
                "scenario": "Never use the word 'simply'.",
                "research": "Prefer the planner source over docs.",
            },
            constraints={"duration_s": {"min": 30, "max": 45}, "max_scenes": 5, "custom_flag": True},
        )
    )
    doc = await svc.revision_document(idea.id, 1)
    assert doc["scenario_brief"].startswith("Hook with a question")
    assert doc["palette"] == {"win_accent": "#FF8800", "accent_top": "#00AAFF"}
    assert doc["instructions"]["scenario"] == "Never use the word 'simply'."
    assert doc["constraints"]["max_scenes"] == 5 and doc["constraints"]["custom_flag"] is True
    await svc.update_idea(idea.id, schemas.IdeaPatch(palette={"win_accent": "#112233"}))
    assert idea.rev == 2 and (await svc.revision_document(idea.id, 2))["palette"] == {"win_accent": "#112233"}


@pytest.mark.parametrize(
    "bad",
    [
        {"palette": {"win_accent": "orange"}},
        {"palette": {"Win Accent": "#FFFFFF"}},
        {"instructions": {"publish": "x"}},
        {"instructions": {"scenario": "x" * 4001}},
        {"constraints": {"max_scenes": 0}},
        {"constraints": {"duration_s": {"min": "soon"}}},
    ],
)
def test_idea_level_settings_are_validated(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        idea_in(**bad)
