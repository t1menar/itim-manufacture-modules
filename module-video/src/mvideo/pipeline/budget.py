"""Usage gate: jobs per UTC day and agent runs per sliding hour (05 section 5).

A limit is temporary, so exceeding it is a `transient` failure with `retry_after` that the core
honours (core-04 C21); it never makes the module "not ready".
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mvideo.db import repo
from mvideo.pipeline.errors import StepError
from mvideo.settings_model import Limits


@dataclass(frozen=True, slots=True)
class GateClosed:
    code: str
    retry_after_s: int
    message: str

    def as_error(self, *, step: str | None = None) -> StepError:
        return StepError(
            "transient", self.code, self.message, step=step, details={"retry_after": self.retry_after_s}
        )


def _seconds(delta: dt.timedelta) -> int:
    return max(1, math.ceil(delta.total_seconds()))


async def check_job_gate(session: AsyncSession, limits: Limits, now: dt.datetime) -> GateClosed | None:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    used = await repo.count_usage(session, "job", day_start)
    if used < limits.max_jobs_per_day:
        return None
    next_day = day_start + dt.timedelta(days=1)
    return GateClosed(
        "daily_job_limit",
        _seconds(next_day - now),
        f"{used} jobs already accepted today (limit {limits.max_jobs_per_day}); retry after the UTC day ends",
    )


async def check_agent_run_gate(session: AsyncSession, limits: Limits, now: dt.datetime) -> GateClosed | None:
    window = dt.timedelta(hours=1)
    used = await repo.count_usage(session, "agent_run", now - window)
    if used < limits.max_agent_runs_per_hour:
        return None
    oldest = await repo.oldest_usage(session, "agent_run", now - window)
    wait = _seconds((oldest + window) - now) if oldest is not None else 60
    return GateClosed(
        "agent_run_rate_limit",
        wait,
        f"{used} agent runs in the last hour (limit {limits.max_agent_runs_per_hour})",
    )
