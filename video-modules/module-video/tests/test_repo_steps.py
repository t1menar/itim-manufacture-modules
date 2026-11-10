from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db import repo
from mvideo.db.models import AgentRun, Check, SandboxRun, Step
from tests.test_repo_runs import T0, new_run


async def a_run(session: AsyncSession) -> uuid.UUID:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
    return run.id


async def test_upsert_creates_then_updates_the_same_row(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        first = await repo.upsert_step(session, run_id, "analysis", 1, input_hash="h1", status="running")
    async with session.begin():
        second = await repo.upsert_step(
            session,
            run_id,
            "analysis",
            1,
            input_hash="h1",
            status="succeeded",
            outputs={"a": {"ref": "s3://x"}},
        )
    assert second.id == first.id
    assert (second.status, second.outputs) == ("succeeded", {"a": {"ref": "s3://x"}})
    async with session.begin():
        count = (await session.execute(text("SELECT count(*) FROM steps"))).scalar_one()
    assert count == 1


async def test_each_try_is_its_own_row(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        a = await repo.upsert_step(session, run_id, "script", 1, input_hash="h")
        b = await repo.upsert_step(session, run_id, "script", 2, input_hash="h")
    assert a.id != b.id


async def test_upsert_rejects_unknown_fields(session: AsyncSession) -> None:
    run_id = await a_run(session)
    with pytest.raises(ValueError, match="unknown step fields"):
        await repo.upsert_step(session, run_id, "script", 1, input_hash="h", statuss="running")


async def test_duplicate_step_try_is_rejected_by_the_schema(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        session.add(Step(run_id=run_id, name="capture", try_=1, input_hash="h"))
    with pytest.raises(IntegrityError):
        async with session.begin():
            session.add(Step(run_id=run_id, name="capture", try_=1, input_hash="h"))


async def test_step_status_is_constrained(session: AsyncSession) -> None:
    run_id = await a_run(session)
    with pytest.raises(IntegrityError):
        async with session.begin():
            await repo.upsert_step(session, run_id, "capture", 1, input_hash="h", status="halfway")


async def test_find_reusable_step_returns_latest_succeeded(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        await repo.upsert_step(session, run_id, "research", 1, input_hash="same", status="failed")
        old = await repo.upsert_step(
            session, run_id, "research", 2, input_hash="same", status="succeeded", finished_at=T0
        )
        new = await repo.upsert_step(
            session, run_id, "research", 3, input_hash="same", status="succeeded",
            finished_at=T0 + dt.timedelta(minutes=5),
        )  # fmt: skip
        await repo.upsert_step(session, run_id, "script", 1, input_hash="same", status="succeeded")
    async with session.begin():
        found = await repo.find_reusable_step(session, "research", "same")
        none = await repo.find_reusable_step(session, "research", "other")
    assert found is not None and found.id == new.id != old.id
    assert none is None


async def test_add_cost_accumulates_on_run_and_step(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        step = await repo.upsert_step(session, run_id, "research", 1, input_hash="h")
        await repo.add_cost(
            session,
            run_id,
            cost_usd="0.4100",
            tokens_in=1000,
            tokens_out=50,
            cache_read_tokens=700,
            cache_write_tokens=200,
            step_id=step.id,
        )
        total = await repo.add_cost(session, run_id, cost_usd=Decimal("1.0000"), tokens_in=500, tokens_out=10)
    assert total == Decimal("1.4100")
    async with session.begin():
        run = await repo.get_run(session, run_id)
        step_row = await session.get(Step, step.id, populate_existing=True)
    assert run is not None and step_row is not None
    assert (run.tokens_in, run.tokens_out) == (1500, 60)
    assert (step_row.cost_usd, step_row.cache_read_tokens, step_row.cache_write_tokens) == (
        Decimal("0.4100"), 700, 200,
    )  # fmt: skip


async def test_concurrent_add_cost_loses_no_update(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as s, s.begin():
        run, _ = await repo.create_run(s, new_run())

    async def add() -> None:
        async with factory() as s, s.begin():
            await repo.add_cost(s, run.id, cost_usd="0.1234", tokens_in=10)

    await asyncio.gather(*(add() for _ in range(20)))
    async with factory() as s:
        fresh = await repo.get_run(s, run.id)
    assert fresh is not None
    assert fresh.cost_usd == Decimal("2.4680")
    assert fresh.tokens_in == 200


async def test_child_rows_are_removed_with_the_run(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        step = await repo.upsert_step(session, run_id, "capture", 1, input_hash="h")
        session.add(
            Check(run_id=run_id, step_id=step.id, check_name="glyphs", status="pass", value=0, limit_value=0)
        )
        session.add(SandboxRun(step_id=step.id, purpose="capture", image="postgres:17"))
        session.add(AgentRun(step_id=step.id, turns=3))
    async with session.begin():
        await session.execute(text("DELETE FROM runs WHERE id = :id"), {"id": run_id})
    async with session.begin():
        for model in (Step, Check, SandboxRun, AgentRun):
            assert (await session.execute(select(model))).first() is None


async def test_check_columns_keep_their_spec_names(session: AsyncSession) -> None:
    run_id = await a_run(session)
    async with session.begin():
        session.add(Check(run_id=run_id, check_name="safe_zone", status="warn", value=2, limit_value=0))
    async with session.begin():
        row = (await session.execute(text('SELECT "check", status, "limit" FROM checks'))).one()
    assert tuple(row) == ("safe_zone", "warn", 0)
