"""Async repository functions over database `video`.

Every function takes an `AsyncSession` and leaves the transaction to the caller, so a later
phase can combine several calls atomically. Time-dependent functions accept `now` so tests
and the runner can control the clock.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mvideo.db.models import ACTIVE_RUN_STATUSES, Run, SourceCache, Step, UsageLog
from mvideo.ids import uuid7

LEASE_TTL_S = 60  # 05 section 2: lease renewed every 20 s, taken for 60 s


def _now(now: dt.datetime | None) -> dt.datetime:
    return now if now is not None else dt.datetime.now(dt.UTC)


@dataclass(frozen=True, slots=True)
class NewRun:
    job_id: uuid.UUID
    attempt: int
    production_id: uuid.UUID
    mode: str
    settings_version: int
    settings: dict[str, Any]
    input: dict[str, Any]
    deadline: dt.datetime
    variant_id: uuid.UUID | None = None
    language: str = "en"
    callback_base_url: str | None = None
    credential_refs: list[str] | None = None
    traceparent: str | None = None


async def create_run(session: AsyncSession, new: NewRun) -> tuple[Run, bool]:
    """Insert a run; a repeated `job_id` returns the existing run (idempotent intake).

    Returns `(run, created)`. The unique constraint, not a read-then-write, decides the race.
    """
    stmt = (
        pg_insert(Run)
        .values(
            id=uuid7(),
            job_id=new.job_id,
            attempt=new.attempt,
            production_id=new.production_id,
            mode=new.mode,
            language=new.language,
            variant_id=new.variant_id,
            settings_version=new.settings_version,
            settings=new.settings,
            input=new.input,
            deadline=new.deadline,
            callback_base_url=new.callback_base_url,
            credential_refs=new.credential_refs,
            traceparent=new.traceparent,
        )
        .on_conflict_do_nothing(index_elements=["job_id"])
        .returning(Run.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    run = await get_run_by_job(session, new.job_id)
    if run is None:  # inserted now or present from before: cannot be missing
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
    """Lease up to `limit` runnable runs, oldest first.

    Runnable: `accepted` (not yet started), or `running` / `cancelling` whose lease expired
    (the process died; recovery resumes them, 05 section 8). Rows locked by another claimer
    are skipped, so two callers never get the same run.
    """
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


async def take_lease(
    session: AsyncSession,
    run_id: uuid.UUID,
    owner: str,
    *,
    ttl_s: int = LEASE_TTL_S,
    now: dt.datetime | None = None,
) -> bool:
    """Take the lease of an active run if it is free, expired or already ours."""
    at = _now(now)
    stmt = (
        update(Run)
        .where(
            Run.id == run_id,
            Run.status.in_(ACTIVE_RUN_STATUSES),
            or_(
                Run.lease_owner.is_(None),
                Run.lease_until.is_(None),
                Run.lease_until < at,
                Run.lease_owner == owner,
            ),
        )
        .values(lease_owner=owner, lease_until=at + dt.timedelta(seconds=ttl_s))
        .returning(Run.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def renew_lease(
    session: AsyncSession,
    run_id: uuid.UUID,
    owner: str,
    *,
    ttl_s: int = LEASE_TTL_S,
    now: dt.datetime | None = None,
) -> bool:
    """Extend our lease. False means the lease was lost to another owner: stop working on the run."""
    at = _now(now)
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.lease_owner == owner)
        .values(lease_until=at + dt.timedelta(seconds=ttl_s))
        .returning(Run.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def release_lease(session: AsyncSession, run_id: uuid.UUID, owner: str) -> None:
    await session.execute(
        update(Run)
        .where(Run.id == run_id, Run.lease_owner == owner)
        .values(lease_owner=None, lease_until=None)
    )


_STEP_ATTRS = {
    "status", "prompt_version", "model", "outputs", "reused_from", "error", "cost_usd", "tokens_in",
    "tokens_out", "cache_read_tokens", "cache_write_tokens", "num_turns", "session_id", "started_at",
    "finished_at", "duration_s",
}  # fmt: skip


async def upsert_step(
    session: AsyncSession,
    run_id: uuid.UUID,
    name: str,
    try_: int,
    *,
    input_hash: str,
    **fields: Any,
) -> Step:
    """Create the step row for `(run, name, try)` or update it in place."""
    unknown = set(fields) - _STEP_ATTRS
    if unknown:
        raise ValueError(f"unknown step fields: {sorted(unknown)}")
    values = {"input_hash": input_hash, **fields}
    stmt = (
        pg_insert(Step)
        .values(id=uuid7(), run_id=run_id, name=name, **{"try": try_}, **values)
        .on_conflict_do_update(constraint="uq_steps_run_name_try", set_=values)
        .returning(Step.id)
    )
    step_id = (await session.execute(stmt)).scalar_one()
    step = await session.get(Step, step_id, populate_existing=True)
    if step is None:
        raise RuntimeError(f"step {name}/{try_} vanished after upsert")
    return step


async def find_reusable_step(session: AsyncSession, name: str, input_hash: str) -> Step | None:
    """Most recent succeeded step with identical inputs, for the step cache (05 section 8)."""
    stmt = (
        select(Step)
        .where(Step.name == name, Step.input_hash == input_hash, Step.status == "succeeded")
        .order_by(Step.finished_at.desc().nulls_last(), Step.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_cost(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    cost_usd: Decimal | float | str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    step_id: uuid.UUID | None = None,
) -> Decimal:
    """Atomically add cost and usage to the run (and the step). Returns the run's new cost total.

    The increments happen in SQL (`col = col + x`), so concurrent agent runs never lose an update.
    """
    cost = Decimal(str(cost_usd))
    total = (
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                cost_usd=Run.cost_usd + cost,
                tokens_in=Run.tokens_in + tokens_in,
                tokens_out=Run.tokens_out + tokens_out,
            )
            .returning(Run.cost_usd)
        )
    ).scalar_one()
    if step_id is not None:
        await session.execute(
            update(Step)
            .where(Step.id == step_id)
            .values(
                cost_usd=Step.cost_usd + cost,
                tokens_in=Step.tokens_in + tokens_in,
                tokens_out=Step.tokens_out + tokens_out,
                cache_read_tokens=Step.cache_read_tokens + cache_read_tokens,
                cache_write_tokens=Step.cache_write_tokens + cache_write_tokens,
            )
        )
    return total


async def list_steps(session: AsyncSession, run_id: uuid.UUID) -> list[Step]:
    result = await session.execute(
        select(Step).where(Step.run_id == run_id).order_by(Step.started_at.nulls_last(), Step.id)
    )
    return list(result.scalars())


async def previous_outputs(
    session: AsyncSession, production_id: uuid.UUID, exclude: uuid.UUID
) -> dict[str, dict[str, Any]] | None:
    """`{step: outputs}` of the latest succeeded run of the production (revise mode), or None."""
    stmt = (
        select(Run)
        .where(Run.production_id == production_id, Run.status == "succeeded", Run.id != exclude)
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    run = (await session.execute(stmt)).scalar_one_or_none()
    if run is None:
        return None
    out: dict[str, dict[str, Any]] = {}
    tries: dict[str, int] = {}
    for row in await list_steps(session, run.id):
        if row.status in ("succeeded", "reused") and row.try_ >= tries.get(row.name, 0):
            out[row.name], tries[row.name] = row.outputs, row.try_
    return out


async def update_progress(
    session: AsyncSession, run_id: uuid.UUID, *, step: str | None, percent: int, message: str | None = None
) -> None:
    del message  # progress text is transient: it goes to the core, not to the database
    await session.execute(update(Run).where(Run.id == run_id).values(current_step=step, percent=percent))


async def request_cancel(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    """Flag an active run for cancellation. Returns the run, or None if it is missing or finished."""
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .values(cancel_requested=True, status="cancelling")
        .returning(Run.id)
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        return None
    return await get_run(session, run_id)


async def store_outcome(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Persist the final payload BEFORE the callback is sent, so a restart can re-send it (05 section 8)."""
    values: dict[str, Any] = {}
    if result is not None:
        values["result"] = result
    if error is not None:
        values["error"] = error
    await session.execute(update(Run).where(Run.id == run_id).values(**values))


async def finish_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    status: str,
    *,
    now: dt.datetime | None = None,
) -> None:
    """Move a run to a final status, stamp the finish time and drop the lease."""
    await session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(status=status, finished_at=_now(now), lease_owner=None, lease_until=None)
    )


async def log_usage(
    session: AsyncSession,
    kind: str,
    run_id: uuid.UUID | None,
    *,
    step: str | None = None,
    at: dt.datetime | None = None,
) -> None:
    await session.execute(
        UsageLog.__table__.insert().values(kind=kind, run_id=run_id, step=step, at=_now(at))
    )


async def count_usage(session: AsyncSession, kind: str, since: dt.datetime) -> int:
    stmt = select(func.count()).select_from(UsageLog).where(UsageLog.kind == kind, UsageLog.at >= since)
    return int((await session.execute(stmt)).scalar_one())


async def oldest_usage(session: AsyncSession, kind: str, since: dt.datetime) -> dt.datetime | None:
    stmt = select(func.min(UsageLog.at)).where(UsageLog.kind == kind, UsageLog.at >= since)
    return (await session.execute(stmt)).scalar_one()


async def upsert_source(
    session: AsyncSession,
    repo_url: str,
    commit: str,
    volume: str,
    size_bytes: int,
    *,
    now: dt.datetime | None = None,
) -> None:
    """Record (or refresh) a cached checkout; `last_used_at` is set to now."""
    at = _now(now)
    stmt = pg_insert(SourceCache).values(
        repo_url=repo_url, commit=commit, volume=volume, size_bytes=size_bytes, created_at=at, last_used_at=at
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["repo_url", "commit"],
            set_={"volume": volume, "size_bytes": size_bytes, "last_used_at": at},
        )
    )


async def get_source(session: AsyncSession, repo_url: str, commit: str) -> SourceCache | None:
    return await session.get(SourceCache, (repo_url, commit))


async def touch_source(
    session: AsyncSession, repo_url: str, commit: str, *, now: dt.datetime | None = None
) -> None:
    await session.execute(
        update(SourceCache)
        .where(SourceCache.repo_url == repo_url, SourceCache.commit == commit)
        .values(last_used_at=_now(now))
    )


async def list_sources(session: AsyncSession) -> list[SourceCache]:
    return list((await session.execute(select(SourceCache).order_by(SourceCache.last_used_at))).scalars())


async def delete_source(session: AsyncSession, repo_url: str, commit: str) -> None:
    row = await session.get(SourceCache, (repo_url, commit))
    if row is not None:
        await session.delete(row)
