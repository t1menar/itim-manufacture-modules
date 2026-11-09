"""Loading idea documents by `idea_ref` (job intake, 05 section 2.1)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mvideo.db.models import Idea, IdeaRevision, Topic
from mvideo.ideas.document import build_document

FROZEN = (
    "queued",
    "dispatched",
    "in_production",
    "done",
    "failed",
)  # content of this rev can no longer change


async def load_document(session: AsyncSession, idea_id: int, rev: int) -> dict[str, Any] | None:
    """The snapshot written at dispatch; else the live row when its rev matches and the content is frozen."""
    snap = await session.get(IdeaRevision, (idea_id, rev))
    if snap is not None:
        return dict(snap.document)
    idea = await session.get(Idea, idea_id)
    if idea is None or idea.rev != rev or idea.status not in FROZEN:
        return None
    topic = await session.get(Topic, idea.topic_id)
    return build_document(idea, topic) if topic is not None else None


async def save_snapshot(session: AsyncSession, doc: dict[str, Any]) -> None:
    stmt = (
        pg_insert(IdeaRevision)
        .values(idea_id=doc["id"], rev=doc["rev"], document=doc)
        .on_conflict_do_nothing(index_elements=["idea_id", "rev"])
    )
    await session.execute(stmt)


async def queued_batch(session: AsyncSession, limit: int) -> list[tuple[Idea, Topic]]:
    stmt = (
        select(Idea, Topic)
        .join(Topic, Topic.id == Idea.topic_id)
        .where(Idea.status == "queued", Topic.active.is_(True))
        .order_by(Idea.priority.desc(), Idea.queued_at, Idea.id)
        .limit(limit)
        .with_for_update(of=Idea, skip_locked=True)
    )
    return [(i, t) for i, t in (await session.execute(stmt)).all()]
