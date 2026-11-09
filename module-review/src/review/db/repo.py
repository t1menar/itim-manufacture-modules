from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from review.db.models import ACTIVE, FINAL, PendingReject, ReviewCard, Run
from review.ids import uuid7

LEASE_TTL_S = 60


def _now(now: dt.datetime | None) -> dt.datetime:
    return now if now is not None else dt.datetime.now(dt.UTC)


@dataclass(frozen=True, slots=True)
class NewRun:
    job_id: uuid.UUID
    attempt: int
    fence: int
    production_id: uuid.UUID
    mode: str
    round: int
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
            round=new.round,
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
        raise RuntimeError("run vanished")
    return run, inserted is not None


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    return await session.get(Run, run_id, populate_existing=True)


async def get_run_by_job(session: AsyncSession, job_id: uuid.UUID) -> Run | None:
    r = await session.execute(
        select(Run).where(Run.job_id == job_id).execution_options(populate_existing=True)
    )
    return r.scalar_one_or_none()


async def claim_runs(
    session: AsyncSession, owner: str, *, limit: int, ttl_s: int = LEASE_TTL_S, now: dt.datetime | None = None
) -> list[Run]:
    at = _now(now)
    # Only claim accepted/running/cancelling — awaiting_* wait for human input.
    stmt = (
        select(Run)
        .where(
            Run.status.in_(("accepted", "running", "cancelling")),
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


async def renew_lease(session: AsyncSession, run_id: uuid.UUID, owner: str, *, now: dt.datetime | None = None) -> bool:
    at = _now(now)
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.lease_owner == owner)
        .values(lease_until=at + dt.timedelta(seconds=LEASE_TTL_S))
        .returning(Run.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def set_status(session: AsyncSession, run_id: uuid.UUID, status: str, *, step: str | None = None) -> None:
    values: dict[str, Any] = {"status": status}
    if step is not None:
        values["step"] = step
    if status in FINAL:
        values["finished_at"] = _now(None)
        values["lease_owner"] = None
        values["lease_until"] = None
    await session.execute(update(Run).where(Run.id == run_id).values(**values))


async def store_outcome(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
            status=status,
            result=result,
            error=error,
            finished_at=_now(None),
            lease_owner=None,
            lease_until=None,
            percent=100 if status == "succeeded" else 0,
        )
    )


async def request_cancel(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    stmt = (
        update(Run)
        .where(Run.id == run_id, Run.status.in_(ACTIVE))
        .values(cancel_requested=True, status="cancelling")
        .returning(Run)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def save_card(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    variant_id: uuid.UUID,
    version: int,
    chat_id: int,
    message_id: int,
) -> ReviewCard:
    # Mark older cards stale
    await session.execute(
        update(ReviewCard)
        .where(ReviewCard.variant_id == variant_id, ReviewCard.version < version)
        .values(stale=True)
    )
    card = ReviewCard(
        id=uuid7(),
        run_id=run_id,
        variant_id=variant_id,
        version=version,
        chat_id=chat_id,
        message_id=message_id,
    )
    session.add(card)
    await session.flush()
    return card


async def latest_card(session: AsyncSession, variant_id: uuid.UUID) -> ReviewCard | None:
    r = await session.execute(
        select(ReviewCard)
        .where(ReviewCard.variant_id == variant_id)
        .order_by(ReviewCard.version.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def card_for_message(session: AsyncSession, chat_id: int, message_id: int) -> ReviewCard | None:
    r = await session.execute(
        select(ReviewCard).where(ReviewCard.chat_id == chat_id, ReviewCard.message_id == message_id)
    )
    return r.scalar_one_or_none()


async def approved_card(session: AsyncSession, variant_id: uuid.UUID) -> ReviewCard | None:
    """Latest non-stale card for variant (the one that was approved)."""
    r = await session.execute(
        select(ReviewCard)
        .where(ReviewCard.variant_id == variant_id, ReviewCard.stale.is_(False))
        .order_by(ReviewCard.version.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def set_pending_reject(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    chat_id: int,
    admin_user_id: int,
    card_message_id: int | None,
    asked_message_id: int | None,
) -> None:
    await session.merge(
        PendingReject(
            run_id=run_id,
            chat_id=chat_id,
            admin_user_id=admin_user_id,
            card_message_id=card_message_id,
            asked_message_id=asked_message_id,
        )
    )


async def get_pending_reject(session: AsyncSession, run_id: uuid.UUID) -> PendingReject | None:
    return await session.get(PendingReject, run_id)


async def find_pending_for_admin(session: AsyncSession, chat_id: int, admin_user_id: int) -> PendingReject | None:
    r = await session.execute(
        select(PendingReject)
        .where(PendingReject.chat_id == chat_id, PendingReject.admin_user_id == admin_user_id)
        .order_by(PendingReject.created_at.desc())
        .limit(1)
    )
    return r.scalar_one_or_none()


async def clear_pending_reject(session: AsyncSession, run_id: uuid.UUID) -> None:
    row = await session.get(PendingReject, run_id)
    if row is not None:
        await session.delete(row)


async def run_by_card_message(session: AsyncSession, chat_id: int, message_id: int) -> Run | None:
    card = await card_for_message(session, chat_id, message_id)
    if card is None:
        return None
    return await get_run(session, card.run_id)
