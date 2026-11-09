"""Job intake, cancel and status for the API layer."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvideo.db import repo
from mvideo.db.models import Run
from mvideo.db.repo import NewRun
from mvideo.intake import ValidJob
from mvideo.pipeline.budget import check_job_gate
from mvideo.pipeline.runner import Runner
from mvideo.pipeline.state import FINAL_RUN_STATUSES
from mvideo.pipeline.worker import Worker


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class JobService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        worker: Worker,
        runner: Runner,
        clock: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        self._factory = factory
        self._worker = worker
        self._runner = runner
        self._clock = clock

    async def accept(self, job: ValidJob, traceparent: str | None) -> Run:
        """Store the run (idempotent on job_id) and apply the daily usage gate (05 section 2.1)."""
        req = job.request
        async with self._factory() as s, s.begin():
            run, created = await repo.create_run(
                s,
                NewRun(
                    job_id=req.job_id,
                    attempt=req.attempt,
                    production_id=req.production_id,
                    mode=req.mode,
                    variant_id=uuid.UUID(str(req.variant["id"])) if req.variant else None,
                    settings_version=req.settings.version,
                    settings=req.settings.values,
                    input=req.input,
                    deadline=req.deadline,
                    callback_base_url=req.callback.base_url,
                    credential_refs=req.credentials,
                    traceparent=traceparent,
                ),
            )
            if created:
                gate = await check_job_gate(s, job.settings.limits, self._clock())
                if gate is None:
                    await repo.log_usage(s, "job", run.id, at=self._clock())
                else:
                    # Accepted, then failed transient: the core retries after `retry_after`.
                    await repo.store_outcome(s, run.id, error=gate.as_error().fail_body())
        if created:
            self._worker.max_parallel = job.settings.runtime.max_parallel_jobs
            self._worker.wake()
        return run

    async def cancel(self, job_id: uuid.UUID) -> tuple[str, Run | None]:
        """Returns ("not_found" | "finished" | "cancelling", run)."""
        async with self._factory() as s, s.begin():
            run = await repo.get_run_by_job(s, job_id)
            if run is None:
                return "not_found", None
            if run.status in FINAL_RUN_STATUSES:
                return "finished", run
            if run.status != "cancelling":
                cancelled = await repo.request_cancel(s, run.id)
                if cancelled is not None:
                    run = cancelled
        self._runner.signal_cancel(run.id)
        self._worker.wake()
        return "cancelling", run

    async def status_document(self, job_id: uuid.UUID) -> dict[str, Any] | None:
        async with self._factory() as s:
            run = await repo.get_run_by_job(s, job_id)
            if run is None:
                return None
            steps = await repo.list_steps(s, run.id)
        error = None
        if run.status == "failed" and run.error:
            details = run.error.get("details", {})
            error = {
                "class": run.error.get("class"),
                "code": details.get("code"),
                "message": run.error.get("message"),
            }
        return {
            "job_id": str(run.job_id),
            "attempt": run.attempt,
            "production_id": str(run.production_id),
            "mode": run.mode,
            "status": run.status,
            "step": run.current_step,
            "percent": run.percent,
            "message": None,
            "steps": [
                {
                    "name": st.name,
                    "status": st.status,
                    "duration_s": st.duration_s,
                    "cost_usd": float(st.cost_usd),
                    "reused": st.status == "reused",
                }
                for st in steps
            ],
            "cost_usd": float(run.cost_usd),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "error": error,
        }
