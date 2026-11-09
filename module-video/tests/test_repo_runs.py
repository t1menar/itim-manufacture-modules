from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db import repo
from mvideo.db.repo import NewRun
from mvideo.ids import uuid7

T0 = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


def new_run(job_id: uuid.UUID | None = None, **kw: Any) -> NewRun:
    return NewRun(
        job_id=job_id or uuid7(),
        attempt=1,
        production_id=uuid7(),
        mode="create",
        settings_version=7,
        settings={"agent": {"image": "x"}},
        input={"idea": {"id": 1, "text": "hello world", "language": "en"}},
        deadline=T0 + dt.timedelta(hours=1),
        **kw,
    )


async def test_create_run_stores_defaults(session: AsyncSession) -> None:
    async with session.begin():
        run, created = await repo.create_run(session, new_run())
    assert created is True
    assert run.status == "accepted"
    assert run.language == "en"
    assert (run.percent, run.cancel_requested) == (0, False)
    assert run.cost_usd == 0
    assert run.id.version == 7


async def test_repeated_job_id_returns_existing_run(factory: async_sessionmaker[AsyncSession]) -> None:
    job = new_run()
    async with factory() as s1, s1.begin():
        first, created_first = await repo.create_run(s1, job)
    async with factory() as s2, s2.begin():
        again, created_again = await repo.create_run(s2, job)
    assert (created_first, created_again) == (True, False)
    assert again.id == first.id
    async with factory() as s3:
        count = (await s3.execute(text("SELECT count(*) FROM runs"))).scalar_one()
    assert count == 1


async def test_parallel_intake_of_the_same_job_creates_one_run(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    job = new_run()

    async def intake() -> tuple[uuid.UUID, bool]:
        async with factory() as s, s.begin():
            run, created = await repo.create_run(s, job)
            return run.id, created

    results = await asyncio.gather(*(intake() for _ in range(8)))
    assert len({rid for rid, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1


async def test_status_and_mode_are_constrained(session: AsyncSession) -> None:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
    with pytest.raises(IntegrityError):
        async with session.begin():
            await session.execute(text("UPDATE runs SET status = 'bogus' WHERE id = :id"), {"id": run.id})
    with pytest.raises(IntegrityError):
        async with session.begin():
            await repo.create_run(session, dataclasses.replace(new_run(), mode="rewrite"))


async def test_lease_take_blocks_others_until_it_expires(session: AsyncSession) -> None:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
    async with session.begin():
        assert await repo.take_lease(session, run.id, "a", ttl_s=60, now=T0) is True
        assert (
            await repo.take_lease(session, run.id, "b", ttl_s=60, now=T0 + dt.timedelta(seconds=59)) is False
        )
        # the owner may take it again (renewal path used by a restarted worker with the same name)
        assert (
            await repo.take_lease(session, run.id, "a", ttl_s=60, now=T0 + dt.timedelta(seconds=30)) is True
        )
    async with session.begin():
        # a's lease now runs to T0+90; after that b can take it
        assert (
            await repo.take_lease(session, run.id, "b", ttl_s=60, now=T0 + dt.timedelta(seconds=91)) is True
        )
    fresh = await repo.get_run(session, run.id)
    assert fresh is not None and fresh.lease_owner == "b"


async def test_renew_only_by_the_owner(session: AsyncSession) -> None:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
        await repo.take_lease(session, run.id, "a", now=T0)
    async with session.begin():
        assert await repo.renew_lease(session, run.id, "b", now=T0) is False
        assert (
            await repo.renew_lease(session, run.id, "a", ttl_s=60, now=T0 + dt.timedelta(seconds=20)) is True
        )
    fresh = await repo.get_run(session, run.id)
    assert fresh is not None and fresh.lease_until == T0 + dt.timedelta(seconds=80)


async def test_release_frees_the_lease(session: AsyncSession) -> None:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
        await repo.take_lease(session, run.id, "a", now=T0)
        await repo.release_lease(session, run.id, "b")  # not the owner: no effect
        assert await repo.take_lease(session, run.id, "c", now=T0 + dt.timedelta(seconds=1)) is False
        await repo.release_lease(session, run.id, "a")
        assert await repo.take_lease(session, run.id, "c", now=T0 + dt.timedelta(seconds=1)) is True


async def test_finished_runs_cannot_be_leased(session: AsyncSession) -> None:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
        await session.execute(text("UPDATE runs SET status = 'succeeded' WHERE id = :id"), {"id": run.id})
        assert await repo.take_lease(session, run.id, "a", now=T0) is False


async def test_claim_runs_takes_oldest_first_and_starts_them(session: AsyncSession) -> None:
    async with session.begin():
        ids = [(await repo.create_run(session, new_run()))[0].id for _ in range(3)]
    async with session.begin():
        claimed = await repo.claim_runs(session, "w1", limit=2, now=T0)
    assert [r.id for r in claimed] == ids[:2]
    assert all(r.status == "running" and r.lease_owner == "w1" and r.started_at == T0 for r in claimed)
    async with session.begin():
        rest = await repo.claim_runs(session, "w2", limit=5, now=T0 + dt.timedelta(seconds=1))
    assert [r.id for r in rest] == ids[2:]  # the first two still hold a valid lease


async def test_claim_runs_resumes_runs_with_expired_lease(session: AsyncSession) -> None:
    async with session.begin():
        run, _ = await repo.create_run(session, new_run())
    async with session.begin():
        await repo.claim_runs(session, "dead-worker", limit=1, ttl_s=60, now=T0)
    async with session.begin():
        assert await repo.claim_runs(session, "w2", limit=1, now=T0 + dt.timedelta(seconds=30)) == []
    async with session.begin():
        resumed = await repo.claim_runs(session, "w2", limit=1, now=T0 + dt.timedelta(seconds=61))
    assert [r.id for r in resumed] == [run.id]
    assert resumed[0].lease_owner == "w2"
    assert resumed[0].started_at == T0  # first start time is kept


async def test_claim_runs_skips_rows_locked_by_a_concurrent_claimer(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s, s.begin():
        for _ in range(5):
            await repo.create_run(s, new_run())
    async with factory() as a, factory() as b:
        await a.begin()
        await b.begin()
        got_a = await repo.claim_runs(a, "a", limit=2, now=T0)
        got_b = await repo.claim_runs(b, "b", limit=5, now=T0)  # a's rows are locked: skipped, not awaited
        await a.commit()
        await b.commit()
    assert len(got_a) == 2 and len(got_b) == 3
    assert not {r.id for r in got_a} & {r.id for r in got_b}
