"""GET /health, /ready, /metrics (04 section 2)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from mvideo.db import repo
from mvideo.db.engine import session_factory

# A check returns None when healthy, or a short reason string when not.
Check = Callable[[], Awaitable[str | None]]
AuthStatus = Callable[[], Awaitable[str]]

router = APIRouter()


async def _failures(checks: list[Check]) -> list[str]:
    reasons: list[str] = []
    for check in checks:
        reason = await check()
        if reason:
            reasons.append(reason)
    return reasons


@router.get("/health")
async def health(request: Request) -> Response:
    """Process alive and database reachable (the database check is registered in phase B1)."""
    reasons = await _failures(request.app.state.health_checks)
    if reasons:
        return JSONResponse({"status": "unavailable", "reasons": reasons}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/ready")
async def ready(request: Request) -> Response:
    """Dependencies usable. A usage or rate limit never makes the module not ready."""
    reasons = await _failures(request.app.state.ready_checks)
    auth = await request.app.state.auth_status()
    body: dict[str, Any] = {"ready": not reasons, "auth": auth}
    if reasons:
        body["reasons"] = reasons
        return JSONResponse(body, status_code=503)
    return JSONResponse(body)


async def _refresh_gauges(request: Request) -> None:
    """Queue and usage gauges are read from the database at scrape time."""
    engine = request.app.state.engine
    if engine is None:
        return
    m = request.app.state.metrics
    now = dt.datetime.now(dt.UTC)
    try:
        async with session_factory(engine)() as s:
            counts = await repo.count_runs_by_status(s)
            m.running.set(counts.get("running", 0) + counts.get("cancelling", 0))
            m.queued.set(counts.get("accepted", 0))
            m.jobs_today.set(
                await repo.count_usage(s, "job", now.replace(hour=0, minute=0, second=0, microsecond=0))
            )
            m.agent_runs_last_hour.set(await repo.count_usage(s, "agent_run", now - dt.timedelta(hours=1)))
    except Exception:  # a scrape must not fail because the database is down
        return


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    await _refresh_gauges(request)
    return Response(generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST)
