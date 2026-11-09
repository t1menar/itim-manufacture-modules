from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.db import repo
from review.db.models import FINAL, Run
from review.db.repo import NewRun
from review.intake import ValidJob
from review.jobs.worker import Worker


class JobService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], worker: Worker) -> None:
        self._factory = factory
        self._worker = worker

    async def accept(self, job: ValidJob) -> Run:
        async with self._factory() as s, s.begin():
            run, created = await repo.create_run(
                s,
                NewRun(
                    job_id=job.job_id,
                    attempt=job.attempt,
                    fence=job.fence,
                    production_id=job.production_id,
                    mode=job.mode,
                    round=job.round,
                    variant_id=job.variant_id,
                    settings=job.settings,
                    input=job.input,
                    deadline=job.deadline,
                    callback_base_url=job.callback_base_url,
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
            "status": run.status,
            "step": run.step,
            "percent": run.percent,
            "result": run.result,
            "error": run.error,
        }
