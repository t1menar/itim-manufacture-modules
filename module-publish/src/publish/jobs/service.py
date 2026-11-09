"""Job intake, cancel and status."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publish.db import repo
from publish.db.models import Run
from publish.db.repo import FINAL, NewRun
from publish.intake import ValidJob
from publish.jobs.worker import Worker


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class JobService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        worker: Worker,
        clock: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        self._factory = factory
        self._worker = worker
        self._clock = clock

    async def accept(self, job: ValidJob) -> Run:
        req = job.request
        async with self._factory() as s, s.begin():
            run, created = await repo.create_run(
                s,
                NewRun(
                    job_id=req.job_id,
                    attempt=req.attempt,
                    fence=req.fence,
                    production_id=req.production_id,
                    mode=req.mode,
                    variant_id=req.variant.id if req.variant else None,
                    settings_version=req.settings.version,
                    settings=req.settings.values,
                    input=req.input,
                    deadline=job.deadline,
                    callback_base_url=req.callback.base_url,
                ),
            )
        if created:
            self._worker.wake()
        return run

    async def cancel(self, job_id: uuid.UUID) -> tuple[str, Run | None]:
        async with self._factory() as s, s.begin():
            run = await repo.get_run_by_job(s, job_id)
            if run is None:
                return "not_found", None
            if run.status in FINAL:
                return "finished", run
            cancelled = await repo.request_cancel(s, run.id)
            if cancelled is not None:
                run = cancelled
        self._worker.wake()
        return "cancelling", run

    async def status_document(self, job_id: uuid.UUID) -> dict[str, Any] | None:
        async with self._factory() as s:
            run = await repo.get_run_by_job(s, job_id)
            if run is None:
                return None
        return {
            "job_id": str(run.job_id),
            "attempt": run.attempt,
            "production_id": str(run.production_id),
            "mode": run.mode,
            "status": run.status,
            "step": run.step,
            "percent": run.percent,
            "error": run.error,
            "result": run.result,
        }
