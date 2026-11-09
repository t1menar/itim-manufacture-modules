"""The idea scheduler (IDEAS.md section 5): `queued` -> `dispatched` with the `idea.ready` outbox row."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db.models import Idea, IdeaOutbox
from mvideo.ideas import repo
from mvideo.ideas.document import build_document, schema_errors
from mvideo.ideas.ids import format_ref, ready_message_id

PRODUCER = "module:video"
EXCHANGE_KEY = "idea.ready"


@dataclass(frozen=True, slots=True)
class SchedulerParams:
    paused: bool = False
    max_dispatch_per_tick: int = 5
    max_in_flight: int = 3  # dispatched + in_production


def ready_envelope(doc: dict, now: dt.datetime) -> dict:
    """Envelope of `idea.ready`: orchestration hints only, never the idea body."""
    return {
        "message_id": str(ready_message_id(doc["id"], doc["rev"])),
        "type": "idea.ready",
        "schema_version": 1,
        "occurred_at": now.isoformat(),
        "producer": PRODUCER,
        "payload": {
            "idea_ref": {"id": doc["id"], "rev": doc["rev"]},
            "language": doc["language"],
            "pipeline_id": doc.get("pipeline_id"),
            "priority": doc["priority"],
        },
    }


async def tick(
    factory: async_sessionmaker[AsyncSession], params: SchedulerParams, now: dt.datetime | None = None
) -> list[str]:
    """One scheduler pass; returns the `idea_ref`s dispatched. Safe to run from several replicas."""
    if params.paused:
        return []
    now = now or dt.datetime.now(dt.UTC)
    sent: list[str] = []
    async with factory() as s, s.begin():
        await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('video.ideas.scheduler'))"))
        in_flight = (
            await s.execute(
                select(func.count()).select_from(Idea).where(Idea.status.in_(("dispatched", "in_production")))
            )
        ).scalar_one()
        room = min(params.max_dispatch_per_tick, params.max_in_flight - in_flight)
        if room <= 0:
            return []
        for idea, topic in await repo.queued_batch(s, room):
            doc = build_document(idea, topic)
            problems = schema_errors("idea", doc)
            if problems:  # an invalid idea must not block the queue
                idea.status, idea.failure, idea.updated_at = (
                    "failed",
                    {"code": "idea_invalid", "message": problems[0][:500]},
                    now,
                )
                continue
            env = ready_envelope(doc, now)
            await repo.save_snapshot(s, doc)
            s.add(IdeaOutbox(message_id=ready_message_id(idea.id, idea.rev), idea_id=idea.id, rev=idea.rev,
                             routing_key=EXCHANGE_KEY, envelope=env))  # fmt: skip
            idea.status, idea.dispatched_at, idea.updated_at = "dispatched", now, now
            idea.last_message_id = ready_message_id(idea.id, idea.rev)
            sent.append(format_ref(idea.id, idea.rev))
    return sent
