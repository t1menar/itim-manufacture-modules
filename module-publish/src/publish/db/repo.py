"""Run repository: idempotent intake, lease claim/renew, cancel, outcomes."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from publish.db.models import ACTIVE_RUN_STATUSES, Run
from publish.ids import uuid7

LEASE_TTL_S = 60
FINAL = frozenset({"succeeded", "failed", "cancelled"})


def _now(now: dt.datetime | None) -> dt.datetime:
    return now if now is not None else dt.datetime.now(dt.UTC)


@dataclass(frozen=True, slots=True)
class NewRun:
    job_id: uuid.UUID
    attempt: int
    fence: int
    production_id: uuid.UUID
    mode: str
    settings_version: int
    settings: dict[str, Any]
    input: dict[str, Any]
    deadline: dt.datetime
    variant_id: uuid.UUID | None = None
    callback_base_url: str | None = None


async def create_run(session: AsyncSession, new: NewRun) -> tuple[Run, bool]:
    stmt = (
        pg_insert(Run)
        .values(
            id=uuid7(),
            job_id=new.job_id,
            attempt=new.attempt,
            fence=new.fence,
            production_id=new.production_id,
            variant_id=new.variant_id,
            mode=new.mode,
            settings_version=new.settings_version,
            settings=new.settings,
            input=new.input,
            deadline=new.deadline,
            callback_base_url=new.callback_base_url,
        )
        .on_conflict_do_nothing(index_elements=["job_id"])
        .returning(Run.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    run = await get_run_by_job(session, new.job_id)
    if run is None:
        raise RuntimeError(f"run for job {new.job_id} vanished after insert")
    return run, inserted is not None


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    return await session.get(Run, run_id, populate_existing=True)


async def get_run_by_job(session: AsyncSession, job_id: uuid.UUID) -> Run | None:
    result = await session.execute(
        select(Run).where(Run.job_id == job_id).execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def claim_runs(
    session: AsyncSession,
    owner: str,
    *,
    limit: int,
    ttl_s: int = LEASE_TTL_S,
    now: dt.datetime | None = None,
) -> list[Run]:
    at = _now(now)
    stmt = (
        select(Run)
        .where(
            Run.status.in_(ACTIVE_RUN_STATUSES),
            or_(Run.lease_until.is_(None), Run.lease_until < at),
        )
        .order_by(Run.created_at, Run.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    runs = list((await session.execute(stmt)).scalars())
    for run in runs:
        run.lease_owner = owner
        run.lease_until = at + dt.timedelta(seconds=ttl_s)
        if run.status == "accepted":
            run.status = "running"
        if run.started_at is None:
            run.started_at = at
    await session.flush()
    return runs


async def renew_lease(
    session: AsyncSession,
    run_id: uuid.UUID,
    owner: str,
    *,
    ttl_s: int = LEASE_TTL_S,
    now: dt.datetime | None = None,
) -> bool:
    at = _now(now)
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.lease_owner == owner)
        .values(lease_until=at + dt.timedelta(seconds=ttl_s))
        .returning(Run.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def request_cancel(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .values(cancel_requested=True, status="cancelling")
        .returning(Run)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def store_outcome(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> None:
    at = _now(now)
    await session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
            status=status,
            result=result,
            error=error,
            finished_at=at,
            lease_owner=None,
            lease_until=None,
            percent=100 if status == "succeeded" else 0,
        )
    )


async def set_progress(
    session: AsyncSession, run_id: uuid.UUID, *, percent: int, step: str
) -> None:
    await session.execute(
        update(Run).where(Run.id == run_id).values(percent=percent, step=step)
    )
