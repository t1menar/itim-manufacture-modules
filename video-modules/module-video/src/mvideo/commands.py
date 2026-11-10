"""Command queue of the module: the core sends `job.requested` / `job.cancel_requested` here.

The queue and its bindings follow the core topology (`module.<id>.commands`: a quorum queue with a
dead-letter queue, bound to `manufacture.commands` by `*.*.<id>`, `notify.<id>` and `cancel.<id>`).
The module declares them itself, with the same arguments as the core, so the start order does not matter.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import httpx
import structlog

from mvideo.api.problems import ProblemError
from mvideo.intake import validate_job
from mvideo.service import JobService

log = structlog.get_logger("commands")
DELIVERY_LIMIT = 5


async def declare_command_queue(channel: Any, module_id: str, prefix: str = "") -> Any:
    """Declare exchanges, the module queue with its dead-letter queue and the bindings; returns the queue."""
    import aio_pika

    commands, events, dlx = (f"{prefix}manufacture.{n}" for n in ("commands", "events", "dlx"))
    ex = {}
    for name in (commands, events, dlx):
        ex[name] = await channel.declare_exchange(name, aio_pika.ExchangeType.TOPIC, durable=True)
    name = f"{prefix}module.{module_id}.commands"
    dlq = await channel.declare_queue(f"{name}.dlq", durable=True, arguments={"x-queue-type": "quorum"})
    await dlq.bind(ex[dlx], routing_key=name)
    queue = await channel.declare_queue(
        name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": DELIVERY_LIMIT,
            "x-dead-letter-exchange": dlx,
            "x-dead-letter-routing-key": name,
        },
    )
    for key in (f"*.*.{module_id}", f"notify.{module_id}", f"cancel.{module_id}"):
        await queue.bind(ex[commands], routing_key=key)
    return queue


class CommandConsumer:
    def __init__(
        self,
        amqp_url: str,
        module_id: str,
        service: JobService,
        *,
        prefix: str = "",
        core_token: str = "",
    ) -> None:
        self._url, self._module_id, self._prefix = amqp_url, module_id, prefix
        self._service = service
        self._token = core_token
        self._task: asyncio.Task[None] | None = None
        self._conn: Any = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="command-consumer")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._conn is not None:
            await self._conn.close()

    async def _run(self) -> None:
        import aio_pika

        self._conn = await aio_pika.connect_robust(self._url)
        channel = await self._conn.channel()
        await channel.set_qos(prefetch_count=4)
        queue = await declare_command_queue(channel, self._module_id, self._prefix)
        log.info("command_consumer_started", queue=queue.name)
        async with queue.iterator() as it:
            async for message in it:
                async with message.process(requeue=False):
                    try:
                        await self.handle(message.body)
                    except Exception:
                        log.exception("command_failed")

    async def handle(self, body: bytes) -> None:
        try:
            envelope = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("command_bad_json")
            return
        kind = envelope.get("type")
        if kind == "job.requested":
            await self._job_requested(envelope)
        elif kind == "job.cancel_requested":
            job = envelope.get("job") or {}
            raw = job.get("job_id") if isinstance(job, dict) else None
            if raw:
                import uuid

                await self._service.cancel(uuid.UUID(str(raw)))
        else:
            log.info("command_ignored", type=kind)

    async def _job_requested(self, envelope: dict[str, Any]) -> None:
        payload = envelope.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        try:
            job = validate_job(payload, await self._service.local_credentials())
            await self._service.accept(job, envelope.get("traceparent"))
        except ProblemError as exc:
            log.warning("job_rejected", code=exc.code, title=str(exc))
            await self._report_rejected(payload, exc)

    async def _report_rejected(self, payload: dict[str, Any], exc: ProblemError) -> None:
        """A job the module cannot take: tell the core now instead of letting it wait for the deadline."""
        base = ((payload.get("callback") or {}).get("base_url") or "").rstrip("/")
        if not base:
            return
        body = {"class": "fatal", "message": str(exc), "details": {"code": exc.code}}
        headers = {"Authorization": f"Bearer {self._token}", "X-Fence": str(payload.get("fence") or 1)}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"{base}/fail", json=body, headers=headers)
        except httpx.HTTPError:
            log.warning("reject_report_failed")
