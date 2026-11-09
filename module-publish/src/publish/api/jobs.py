"""Job and notify HTTP surface. Phase 1: auth + explicit not_implemented (no fake success)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from publish.api.auth import CoreAuth, Unauthorized, unauthorized_response
from publish.api.problems import problem

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
    await request.body()
    return problem(501, "not_implemented", "Notify is implemented in phase 6")


def install_auth_handler(app: Any) -> None:
    from fastapi import Request as FRequest
    from fastapi.responses import JSONResponse

    async def _unauth(_: FRequest, __: Unauthorized) -> JSONResponse:
        resp = unauthorized_response()
        if not isinstance(resp, JSONResponse):
            raise TypeError("unauthorized_response must return JSONResponse")
        return resp

    app.add_exception_handler(Unauthorized, _unauth)
