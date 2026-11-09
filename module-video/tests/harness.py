"""Wires the app, worker and runner against real PostgreSQL and S3, with a recording fake core."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from mvideo.app import create_app
from mvideo.config import BootstrapConfig
from mvideo.db import repo
from mvideo.db.engine import session_factory
from mvideo.db.models import Run
from mvideo.pipeline.runner import Runner
from mvideo.pipeline.steps.fake import FakeStep, fake_finalize, fake_pipeline
from mvideo.pipeline.worker import Worker
from mvideo.service import JobService
from mvideo.storage import Storage
from tests.helpers import FakeCore, job_request, seed_idea

TOKEN = "test-token"


@dataclass
class Harness:
    app: Any
    core: FakeCore
    steps: list[FakeStep]
    worker: Worker
    runner: Runner
    service: JobService
    factory: async_sessionmaker[AsyncSession]
    storage: Storage

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://module",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    async def submit(self, **kw: Any) -> dict[str, Any]:
        """POST a job through the API; returns the request body (so tests know the job id)."""
        title = kw.pop("input_text", None)  # a different idea text means a different idea revision
        if title is not None:
            kw["idea_ref"] = {"id": 42, "rev": 2 + zlib.crc32(title.encode()) % 1000}
        body = job_request(**kw)
        ref = body["input"]["idea_ref"]
        await seed_idea(
            self.factory,
            idea_id=ref["id"],
            rev=ref["rev"],
            **({"title": title} if title else {}),
        )  # the idea the job refers to must be in this module's database
        async with self.client() as c:
            resp = await c.post("/v1/jobs", json=body)
        assert resp.status_code == 202, resp.text
        return body

    async def run_all(self, limit_s: float = 20.0) -> None:
        """Claim and execute everything runnable until the worker is idle."""

        async def loop() -> None:
            while True:
                claimed = await self.worker.run_once()
                if not claimed and self.worker.running == 0:
                    return
                await self.worker.drain()

        await asyncio.wait_for(loop(), limit_s)

    async def run_row(self, body: dict[str, Any]) -> Run:
        async with self.factory() as s:
            run = await repo.get_run_by_job(s, uuid.UUID(body["job_id"]))
        assert run is not None
        return run

    async def step_rows(self, body: dict[str, Any]) -> dict[str, Any]:
        run = await self.run_row(body)
        async with self.factory() as s:
            return {st.name: st for st in await repo.list_steps(s, run.id)}


def build_harness(
    engine: AsyncEngine,
    storage: Storage,
    config: BootstrapConfig,
    *,
    core: FakeCore | None = None,
    steps: list[FakeStep] | None = None,
    clock: Callable[[], dt.datetime] | None = None,
    **app_kw: Any,
) -> Harness:
    core = core or FakeCore()
    steps = steps if steps is not None else fake_pipeline()
    app = create_app(
        config,
        engine=engine,
        storage=storage,
        core=core,
        steps=steps,
        finalize=fake_finalize,
        worker_poll_s=0.05,
        lease_renew_s=app_kw.pop("lease_renew_s", 0.05),
        cancel_poll_s=0.05,
        **app_kw,
    )
    worker: Worker = app.state.worker
    runner: Runner = app.state.runner
    if clock is not None:
        worker._clock = clock
        runner._clock = clock
        app.state.service._clock = clock
    return Harness(app, core, steps, worker, runner, app.state.service, session_factory(engine), storage)


class Blocker:
    """A step hook that signals it has started and then waits to be released."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, ctx: Any) -> None:
        self.started.set()
        await self.release.wait()
