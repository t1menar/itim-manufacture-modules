"""Outbox relay: publishes pending `idea.ready` rows to RabbitMQ (`manufacture.events`)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db.models import IdeaOutbox


class Publisher(Protocol):
    async def publish(self, routing_key: str, body: bytes, *, message_id: str, type_: str) -> None:
        """Publish with confirm; raises when the broker did not take the message."""
        ...


async def relay_once(factory: async_sessionmaker[AsyncSession], publisher: Publisher, batch: int = 50) -> int:
    """Publish up to `batch` pending rows in order; rows published before an error stay marked."""
    done = 0
    error: Exception | None = None
    async with factory() as s, s.begin():
        stmt = (
            select(IdeaOutbox)
            .where(IdeaOutbox.published_at.is_(None))
            .order_by(IdeaOutbox.created_at, IdeaOutbox.id)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
        for row in (await s.execute(stmt)).scalars():
            env: dict[str, Any] = row.envelope
            try:
                await publisher.publish(
                    row.routing_key,
                    json.dumps(env).encode(),
                    message_id=str(row.message_id),
                    type_=env["type"],
                )
            except Exception as exc:  # keep what was published, then report
                error = exc
                break
            row.published_at = dt.datetime.now(dt.UTC)
            done += 1
    if error is not None:
        raise error
    return done


class AmqpPublisher:
    """aio-pika publisher with confirms; the dependency is imported on first use."""

    def __init__(self, url: str, prefix: str = "") -> None:
        self._url, self._prefix = url, prefix
        self._conn: Any = None
        self._exchange: Any = None

    async def _ensure(self) -> Any:
        if self._exchange is None:
            import aio_pika

            self._conn = await aio_pika.connect_robust(self._url)
            channel = await self._conn.channel(publisher_confirms=True)
            self._exchange = await channel.declare_exchange(
                self._prefix + "manufacture.events", aio_pika.ExchangeType.TOPIC, durable=True
            )
        return self._exchange

    async def publish(self, routing_key: str, body: bytes, *, message_id: str, type_: str) -> None:
        import aio_pika

        exchange = await self._ensure()
        msg = aio_pika.Message(
            body, message_id=message_id, type=type_, content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )  # fmt: skip
        await exchange.publish(msg, routing_key=routing_key)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
