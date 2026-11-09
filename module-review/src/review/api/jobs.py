"""Job and notify HTTP surface."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from review.api.auth import CoreAuth, Unauthorized, unauthorized_response
from review.api.problems import problem

router = APIRouter(tags=["jobs"])


@router.post("/v1/jobs")
async def accept_job(request: Request, _: CoreAuth) -> Any:
    await request.body()
    return problem(
        501,
        "not_implemented",
        "Job intake is implemented in phase 3 (module API + Core client)",
    )


@router.get("/v1/jobs/{job_id}")
async def get_job(job_id: UUID, _: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Job status is implemented in phase 3")


@router.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, _: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Cancel is implemented in phase 3")


@router.post("/v1/notify")
async def notify(request: Request, _: CoreAuth) -> Any:
    body = await request.json()
    if not isinstance(body, dict):
        return problem(422, "validation_error", "notify body must be a JSON object")
    handler = getattr(request.app.state, "notify_handler", None)
    if handler is None:
        return problem(501, "not_implemented", "Notify handler not configured")
    factory = request.app.state.session_factory
    async with factory() as session, session.begin():
        result = await handler.handle_http(session, body)
    return JSONResponse(
        status_code=200,
        content={"ok": True, "claimed": result.claimed, "sent": result.sent, "status": result.status},
    )


def install_auth_handler(app: Any) -> None:
    from fastapi import Request as FRequest
    from fastapi.responses import JSONResponse as JR

    async def _unauth(_: FRequest, __: Unauthorized) -> JR:
        resp = unauthorized_response()
        if not isinstance(resp, JR):
            raise TypeError("unauthorized_response must return JSONResponse")
        return resp

    app.add_exception_handler(Unauthorized, _unauth)
