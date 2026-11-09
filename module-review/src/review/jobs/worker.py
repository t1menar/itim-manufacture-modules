from __future__ import annotations

import asyncio
import contextlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.db import repo
from review.jobs.flow import ReviewFlow
from review.observability.logging import get_logger

log = get_logger(__name__)


class Worker:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        flow: ReviewFlow,
        *,
        max_parallel: int = 4,
        poll_s: float = 0.5,
    ) -> None:
        self._factory = factory
        self._flow = flow
        self.max_parallel = max_parallel
        self._poll = poll_s
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._loop: asyncio.Task[None] | None = None
        self._poll_updates: asyncio.Task[None] | None = None

    def wake(self) -> None:
        self._wake.set()

    async def run_once(self) -> list[uuid.UUID]:
        free = self.max_parallel - len(self._tasks)
        if free <= 0:
            return []
        async with self._factory() as s, s.begin():
            runs = await repo.claim_runs(s, "review-worker-1", limit=free)
        for run in runs:
            rid = run.id

            def _done(_t: asyncio.Task[None], run_id: uuid.UUID = rid) -> None:
                self._tasks.pop(run_id, None)

            task = asyncio.create_task(self._flow.deliver_card(rid), name=f"review-{rid}")
            self._tasks[rid] = task
            task.add_done_callback(_done)
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

    async def _poll_bot(self) -> None:
        bot = getattr(self._flow, "_bot", None)
        while True:
            try:
                if bot is not None and hasattr(bot, "poll"):
                    for upd in bot.poll():
                        await self._flow.handle_update(upd)
            except Exception:
                log.exception("bot_poll_failed")
            await asyncio.sleep(0.2)

    def start(self, *, use_fake_poll: bool = True) -> None:
        if self._loop is None:
            self._loop = asyncio.create_task(self._loop_forever(), name="review-worker")
        if use_fake_poll and self._poll_updates is None:
            self._poll_updates = asyncio.create_task(self._poll_bot(), name="review-bot-poll")

    async def stop(self) -> None:
        for t in (self._loop, self._poll_updates):
            if t is not None:
                t.cancel()
                await asyncio.gather(t, return_exceptions=True)
        self._loop = None
        self._poll_updates = None
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
