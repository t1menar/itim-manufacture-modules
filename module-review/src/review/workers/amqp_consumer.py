"""AMQP command consumer with DB inbox dedup (module contract 2 path).

When REVIEW_AMQP_URL is unset the consumer is not started. Deliveries are
acknowledged after a successful inbox claim; duplicates are acked without re-work.
Job application itself is not implemented in phase 1 — claimed messages are logged
and left for phase 3 (explicit not_implemented in the HTTP twin).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import async_sessionmaker

from review.db.inbox import try_claim
from review.observability.logging import get_logger

log = get_logger(__name__)


class AmqpConsumer:
    def __init__(
        self,
        url: str,
        queue: str,
        session_factory: async_sessionmaker[Any],
        *,
        notify_handler: Any | None = None,
        job_service: Any | None = None,
    ) -> None:
        self._url = url
        self._queue = queue
        self._sessions = session_factory
        self._notify = notify_handler
        self._jobs = job_service
        self._task: asyncio.Task[None] | None = None
        self._conn: aio_pika.RobustConnection | None = None
        self.ready: str = "starting"

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="amqp-consumer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._conn:
            await self._conn.close()
        self.ready = "stopped"

    async def _run(self) -> None:
        try:
            self._conn = await aio_pika.connect_robust(self._url)
            channel = await self._conn.channel()
            await channel.set_qos(prefetch_count=8)
            queue = await channel.declare_queue(self._queue, durable=True)
            self.ready = "ok"
            log.info("amqp_consumer_started", queue=self._queue)
            async with queue.iterator() as it:
                async for message in it:
                    async with message.process(requeue=False):
                        await self._handle(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.ready = f"error:{type(exc).__name__}"
            log.error("amqp_consumer_failed", error=str(exc))
            raise

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        message_id = message.message_id or (message.headers.get("message_id") if message.headers else None)
        if not message_id:
            message_id = message.correlation_id or f"body:{hash(message.body)}"
        try:
            envelope = json.loads(message.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("amqp_bad_json", message_id=str(message_id))
            return
        msg_type = str(envelope.get("type") or message.type or "unknown")
        if msg_type == "notify.requested" and self._notify is not None:
            payload = envelope.get("payload") or envelope
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            await self._notify.handle(str(message_id), payload if isinstance(payload, dict) else {})
            return
        if msg_type == "job.requested" and self._jobs is not None:
            from review.intake import validate_job

            payload = envelope.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            try:
                job = validate_job(payload)
                await self._jobs.accept(job)
            except Exception as exc:
                log.warning("amqp_job_reject", error=str(exc))
            return
        if msg_type == "job.cancel_requested" and self._jobs is not None:
            from uuid import UUID

            job_ref = envelope.get("job") or {}
            raw_id = job_ref.get("job_id") if isinstance(job_ref, dict) else None
            if raw_id:
                try:
                    await self._jobs.cancel(UUID(str(raw_id)))
                except Exception as exc:
                    log.warning("amqp_cancel_failed", error=str(exc))
            return
        async with self._sessions() as session, session.begin():
            claimed = await try_claim(session, str(message_id), msg_type)
        if not claimed:
            log.info("amqp_duplicate", message_id=str(message_id), type=msg_type)
            return
        log.info(
            "amqp_claimed_unhandled",
            message_id=str(message_id),
            type=msg_type,
            note="job application not_implemented until phase 3",
        )
