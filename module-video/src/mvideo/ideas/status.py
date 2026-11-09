"""Reverse idea statuses from core (IDEAS.md section 6.3): inbox dedup and monotonic transitions."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db.models import AmqpInbox, Idea
from mvideo.ideas.document import schema_errors

STATUS_TYPES = ("idea.in_production", "idea.done", "idea.failed")
FROM = {  # target status -> statuses it may follow; anything else is stale (late, duplicate or out of order)
    "in_production": ("dispatched",),
    "done": ("dispatched", "in_production"),
    "failed": ("dispatched", "in_production"),
}


def envelope_problems(env: Any) -> list[str]:
    """Envelope and payload checked against the shared schemas; the type must match the payload status."""
    if not isinstance(env, dict):
        return ["envelope is not an object"]
    problems = schema_errors("envelope", env)
    if env.get("type") not in STATUS_TYPES:
        problems.append(f"type {env.get('type')!r} is not an idea status")
        return problems
    problems += schema_errors("idea.status", env.get("payload"))
    payload = env.get("payload")
    if isinstance(payload, dict) and f"idea.{payload.get('status')}" != env.get("type"):
        problems.append("payload.status does not match the envelope type")
    if isinstance(payload, dict) and payload.get("status") == "failed" and not payload.get("failure"):
        problems.append("a failed status needs a failure object")  # the schema only requires the key
    return problems


async def process_message(
    factory: async_sessionmaker[AsyncSession], body: bytes, now: dt.datetime | None = None
) -> str:
    """Apply one status message; returns `applied`, `stale`, `unknown`, `duplicate` or `invalid`.

    The inbox row and the status change commit together, so a redelivery after a crash is applied once.
    """
    try:
        env = json.loads(body)
    except ValueError:
        return "invalid"
    if envelope_problems(env):
        return "invalid"
    now = now or dt.datetime.now(dt.UTC)
    payload = env["payload"]
    async with factory() as s, s.begin():
        outcome = await _apply(s, env, payload, now)
        return outcome


async def _apply(s: AsyncSession, env: dict[str, Any], payload: dict[str, Any], now: dt.datetime) -> str:
    message_id = uuid.UUID(env["message_id"])
    claimed = (
        await s.execute(
            pg_insert(AmqpInbox)
            .values(message_id=message_id, type=env["type"], outcome="applied")
            .on_conflict_do_nothing(index_elements=["message_id"])
            .returning(AmqpInbox.message_id)
        )
    ).scalar_one_or_none()
    if claimed is None:
        return "duplicate"
    ref = payload["idea_ref"]
    idea = await s.get(Idea, ref["id"], with_for_update=True)
    outcome = "applied"
    if idea is None:
        outcome = "unknown"
    elif idea.rev != ref["rev"] or idea.status not in FROM[payload["status"]]:
        outcome = "stale"
    else:
        idea.status, idea.updated_at = payload["status"], now
        idea.failure = payload.get("failure") if payload["status"] == "failed" else None
    if outcome != "applied":
        inbox = await s.get(AmqpInbox, message_id)
        assert inbox is not None  # noqa: S101
        inbox.outcome = outcome
    return outcome
