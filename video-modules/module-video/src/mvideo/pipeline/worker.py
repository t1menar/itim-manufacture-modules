"""Claims runnable runs and executes them, at most `max_parallel` at a time (05 section 8)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import uuid
from collections.abc import Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db import repo
from mvideo.pipeline.runner import Runner

log = structlog.get_logger()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Worker:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        runner: Runner,
        max_parallel: int = 1,
        poll_s: float = 1.0,
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

    @property
    def running(self) -> int:
        return len(self._tasks)

    def wake(self) -> None:
        self._wake.set()

    async def run_once(self) -> list[uuid.UUID]:
        """Claim free slots and start the runs. Returns the claimed run ids."""
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
            log.info("run_claimed", run_id=str(run.id), status=run.status)
        return [r.id for r in runs]

    async def drain(self) -> None:
        """Wait for everything started so far (tests)."""
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
            self._loop = asyncio.create_task(self._loop_forever(), name="worker-loop")

    async def stop(self) -> None:
        """Stop claiming and tear down running runs WITHOUT marking them failed: their leases
        expire and the next start resumes them."""
        if self._loop is not None:
            self._loop.cancel()
            await asyncio.gather(self._loop, return_exceptions=True)
            self._loop = None
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
