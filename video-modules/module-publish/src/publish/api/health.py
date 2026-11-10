"""GET /health and GET /ready."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

Check = Callable[[], Awaitable[str | None]]

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    checks: list[Check] = getattr(request.app.state, "health_checks", [])
    reasons: list[str] = []
    for check in checks:
        reason = await check()
        if reason:
            reasons.append(reason)
    if reasons:
        return JSONResponse({"status": "down", "reasons": reasons}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Ready shape of 03 §6.3. Unimplemented checks report not_implemented (phase 1)."""
    holder = request.app.state.settings_holder
    checks: dict[str, Any] = {
        "db": getattr(request.app.state, "db_ready", "not_implemented"),
        "settings": holder.source,
        "instagram": "not_implemented",
        "poller": "not_implemented",
        "storage": "not_implemented",
        "core": "not_implemented",
        "amqp": getattr(request.app.state, "amqp_ready", "not_configured"),
    }
    db = checks["db"]
    settings_ok = checks["settings"] in ("defaults", "live", "cached")
    db_ok = db in ("ok", "not_implemented")
    ready_flag = bool(settings_ok and db_ok)
    body: dict[str, Any] = {
        "status": "ready" if ready_flag else "not_ready",
        "checks": checks,
        "ready": ready_flag,
    }
    return JSONResponse(body, status_code=200 if ready_flag else 503)
