"""Claim runnable runs and execute them with a lease."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publish.db import repo
from publish.jobs.runner import JobRunner
from publish.observability.logging import get_logger

log = get_logger(__name__)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Worker:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        runner: JobRunner,
        max_parallel: int = 2,
        poll_s: float = 0.5,
        lease_ttl_s: int = 60,
        clock: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        self._factory = factory
        self._runner = runner
        self.max_parallel = max_parallel
        self._poll = poll_s
        self._ttl = lease_ttl_s
        self._clock = clock
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._loop: asyncio.Task[None] | None = None

    def wake(self) -> None:
        self._wake.set()

    async def run_once(self) -> list[uuid.UUID]:
        free = self.max_parallel - len(self._tasks)
        if free <= 0:
            return []
        async with self._factory() as s, s.begin():
            runs = await repo.claim_runs(
                s, self._runner.owner, limit=free, ttl_s=self._ttl, now=self._clock()
            )
        for run in runs:
            task = asyncio.create_task(self._runner.execute(run.id), name=f"run-{run.id}")
            self._tasks[run.id] = task
            task.add_done_callback(lambda _t, rid=run.id: self._tasks.pop(rid, None))
            log.info("run_claimed", run_id=str(run.id), job_id=str(run.job_id))
        return [r.id for r in runs]

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def _loop_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("claim_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll)
            self._wake.clear()

    def start(self) -> None:
        if self._loop is None:
            self._loop = asyncio.create_task(self._loop_forever(), name="publish-worker")

    async def stop(self) -> None:
        if self._loop is not None:
            self._loop.cancel()
            await asyncio.gather(self._loop, return_exceptions=True)
            self._loop = None
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
