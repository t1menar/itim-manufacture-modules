"""Background loops of the idea flow: scheduler tick, outbox relay, status consumer."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.ideas import relay, scheduler, status

log = structlog.get_logger("ideas")
STATUS_KEYS = ("idea.in_production", "idea.done", "idea.failed")


class IdeaRuntime:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        publisher: relay.Publisher,
        params: scheduler.SchedulerParams,
        *,
        tick_s: float = 5.0,
        amqp_url: str | None = None,
        prefix: str = "",
    ) -> None:
        self._factory, self._publisher, self._params, self._tick_s = factory, publisher, params, tick_s
        self._url, self._prefix = amqp_url, prefix
        self._tasks: list[asyncio.Task[None]] = []
        self._conn: Any = None

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._loop(self._once), name="idea-scheduler")]
        if self._url:
            self._tasks.append(asyncio.create_task(self._consume(), name="idea-status-consumer"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        if self._conn is not None:
            await self._conn.close()
        close = getattr(self._publisher, "close", None)
        if close is not None:
            await close()

    async def _once(self) -> None:
        sent = await scheduler.tick(self._factory, self._params)
        if sent:
            log.info("ideas_dispatched", refs=sent)
        await relay.relay_once(self._factory, self._publisher)

    async def _loop(self, fn: Any) -> None:
        while True:
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("idea_loop_error", error=type(exc).__name__)
            await asyncio.sleep(self._tick_s)

    async def _consume(self) -> None:
        """Queue `module.video.idea-status` on `manufacture.events`, quorum with a DLQ (as core declares)."""
        import aio_pika

        p = self._prefix
        queue_name = p + "module.video.idea-status"
        while True:
            try:
                self._conn = await aio_pika.connect_robust(self._url)
                ch = await self._conn.channel()
                await ch.set_qos(prefetch_count=8)
                events = await ch.declare_exchange(
                    p + "manufacture.events", aio_pika.ExchangeType.TOPIC, durable=True
                )
                dlx = await ch.declare_exchange(
                    p + "manufacture.dlx", aio_pika.ExchangeType.TOPIC, durable=True
                )
                dlq = await ch.declare_queue(
                    queue_name + ".dlq", durable=True, arguments={"x-queue-type": "quorum"}
                )
                await dlq.bind(dlx, routing_key=queue_name)
                queue = await ch.declare_queue(queue_name, durable=True, arguments={
                    "x-queue-type": "quorum", "x-delivery-limit": 5,
                    "x-dead-letter-exchange": p + "manufacture.dlx", "x-dead-letter-routing-key": queue_name,
                })  # fmt: skip
                for key in STATUS_KEYS:
                    await queue.bind(events, routing_key=key)
                async with queue.iterator() as it:
                    async for message in it:
                        # a DB error requeues the message; invalid ones are recorded in the log and dropped
                        async with message.process(requeue=True):
                            outcome = await status.process_message(self._factory, message.body)
                            log.info("idea_status", outcome=outcome, message_id=message.message_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("idea_consumer_error", error=type(exc).__name__)
                await asyncio.sleep(5)
