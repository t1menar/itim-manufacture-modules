"""Run repository: idempotent intake, lease claim/renew, cancel, outcomes."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from publish.db.models import ACTIVE_RUN_STATUSES, PlatformAccount, PublishIntent, PublishLedger, Run
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
    if inserted is None:
        # Same job re-issued by core with a higher fence (take-over): the newer request wins and
        # the run starts over; a task still executing the old fence is fenced out before publishing.
        bumped = (
            await session.execute(
                update(Run)
                .where(Run.job_id == new.job_id, Run.fence < new.fence)
                .values(
                    fence=new.fence,
                    attempt=new.attempt,
                    input=new.input,
                    deadline=new.deadline,
                    callback_base_url=new.callback_base_url,
                    status="accepted",
                    cancel_requested=False,
                    lease_owner=None,
                    lease_until=None,
                    result=None,
                    error=None,
                    finished_at=None,
                )
                .returning(Run.id)
            )
        ).scalar_one_or_none()
        inserted = bumped
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
    fence: int | None = None,
) -> None:
    """fence: only store when the run still has this fence (a superseded task must not overwrite)."""
    at = _now(now)
    cond = [Run.id == run_id]
    if fence is not None:
        cond.append(Run.fence == fence)
    await session.execute(
        update(Run)
        .where(*cond)
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


async def set_progress(session: AsyncSession, run_id: uuid.UUID, *, percent: int, step: str) -> None:
    await session.execute(update(Run).where(Run.id == run_id).values(percent=percent, step=step))


async def list_enabled_accounts(
    session: AsyncSession, *, channel_ids: list[str] | None = None
) -> list[PlatformAccount]:
    stmt = select(PlatformAccount).where(PlatformAccount.enabled.is_(True))
    if channel_ids:
        stmt = stmt.where(PlatformAccount.channel_id.in_(channel_ids))
    result = await session.execute(stmt.order_by(PlatformAccount.created_at))
    return list(result.scalars().all())


async def upsert_local_intent(
    session: AsyncSession,
    *,
    intent_id: uuid.UUID,
    variant_id: uuid.UUID | None,
    platform_account_id: uuid.UUID,
    generation: int,
    content_revision_id: uuid.UUID | None,
    status: str,
    external_post_id: str | None = None,
    url: str | None = None,
    published_at: dt.datetime | None = None,
    last_error: dict[str, Any] | None = None,
) -> None:
    """Mirror core orchestration intent into module-publish's domain table (D23)."""
    if variant_id is None or content_revision_id is None:
        return
    existing = await session.get(PublishIntent, intent_id)
    if existing is None:
        session.add(
            PublishIntent(
                id=intent_id,
                variant_id=variant_id,
                platform_account_id=platform_account_id,
                generation=generation,
                content_revision_id=content_revision_id,
                status=status,
                external_post_id=external_post_id,
                url=url,
                published_at=published_at,
                last_error=last_error,
            )
        )
        return
    existing.status = status
    existing.platform_account_id = platform_account_id
    existing.generation = generation
    if external_post_id is not None:
        existing.external_post_id = external_post_id
    if url is not None:
        existing.url = url
    if published_at is not None:
        existing.published_at = published_at
    if last_error is not None:
        existing.last_error = last_error


async def get_platform_account(session: AsyncSession, account_id: uuid.UUID) -> PlatformAccount | None:
    return await session.get(PlatformAccount, account_id)


# --- publish ledger (no double posts) -----------------------------------------------------------

LEDGER_FINAL_NO_REPOST = frozenset({"publishing", "published", "unknown"})


async def ledger_lock(session: AsyncSession, intent_key: str, account_id: str) -> PublishLedger | None:
    result = await session.execute(
        select(PublishLedger)
        .where(PublishLedger.intent_key == intent_key, PublishLedger.account_id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def ledger_claim(
    session: AsyncSession,
    *,
    intent_key: str,
    account_id: str,
    run_id: uuid.UUID,
    fence: int,
    caption: str | None,
    now: dt.datetime | None = None,
) -> None:
    """Own the intent for this run. Only call when the row is absent, claimed or failed."""
    at = _now(now)
    stmt = pg_insert(PublishLedger).values(
        intent_key=intent_key,
        account_id=account_id,
        status="claimed",
        run_id=run_id,
        fence=fence,
        caption=caption,
        claimed_at=at,
        updated_at=at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["intent_key", "account_id"],
        set_={
            "status": "claimed",
            "run_id": run_id,
            "fence": fence,
            "caption": caption,
            "container_id": None,
            "claimed_at": at,
            "updated_at": at,
        },
        where=PublishLedger.status.in_(("claimed", "failed")),
    )
    await session.execute(stmt)


async def ledger_arm(
    session: AsyncSession,
    *,
    intent_key: str,
    account_id: str,
    run_id: uuid.UUID,
    fence: int,
    container_id: str,
    not_after: dt.datetime,
    now: dt.datetime | None = None,
) -> str | None:
    """Atomically take the right to call media_publish. Returns None when allowed, else the reason.

    Allowed only while the run is live with the same fence, not cancelled, before not_after, and
    still the owner of the claim. On success the row becomes publishing (never posted again).
    """
    at = _now(now)
    run = (
        await session.execute(
            select(Run).where(Run.id == run_id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if run is None:
        return "run_missing"
    if run.fence != fence:
        return "superseded"
    if run.cancel_requested or run.status not in ACTIVE_RUN_STATUSES:
        return "cancelled"
    if at >= not_after:
        return "timeout"
    armed = (
        await session.execute(
            update(PublishLedger)
            .where(
                PublishLedger.intent_key == intent_key,
                PublishLedger.account_id == account_id,
                PublishLedger.run_id == run_id,
                PublishLedger.fence == fence,
                PublishLedger.status == "claimed",
            )
            .values(status="publishing", container_id=container_id, updated_at=at)
            .returning(PublishLedger.intent_key)
        )
    ).scalar_one_or_none()
    return None if armed is not None else "claim_lost"


async def ledger_set(
    session: AsyncSession,
    *,
    intent_key: str,
    account_id: str,
    status: str,
    external_post_id: str | None = None,
    url: str | None = None,
    published_at: dt.datetime | None = None,
    clear_container: bool = False,
    now: dt.datetime | None = None,
) -> None:
    values: dict[str, Any] = {"status": status, "updated_at": _now(now)}
    if external_post_id is not None:
        values["external_post_id"] = external_post_id
    if url is not None:
        values["url"] = url
    if published_at is not None:
        values["published_at"] = published_at
    if clear_container:
        values["container_id"] = None
    await session.execute(
        update(PublishLedger)
        .where(PublishLedger.intent_key == intent_key, PublishLedger.account_id == account_id)
        .values(**values)
    )
