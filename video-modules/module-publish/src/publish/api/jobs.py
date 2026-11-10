"""Job and notify HTTP surface."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from publish.api.auth import CoreAuth, Unauthorized, unauthorized_response
from publish.api.problems import ProblemError, problem
from publish.intake import validate_job

router = APIRouter(tags=["jobs"])


@router.post("/v1/jobs")
async def accept_job(request: Request, _: CoreAuth) -> Any:
    raw = await request.json()
    job = validate_job(raw)
    service = request.app.state.job_service
    if service is None:
        return problem(501, "not_implemented", "Job service not configured")
    run = await service.accept(job)
    return JSONResponse({"job_id": str(run.job_id), "status": run.status}, status_code=202)


@router.get("/v1/jobs/{job_id}")
async def get_job(job_id: UUID, request: Request, _: CoreAuth) -> Any:
    service = request.app.state.job_service
    if service is None:
        return problem(501, "not_implemented", "Job service not configured")
    doc = await service.status_document(job_id)
    if doc is None:
        raise ProblemError(404, "not_found", "Job not found")
    return doc


@router.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, request: Request, _: CoreAuth) -> Any:
    service = request.app.state.job_service
    if service is None:
        return problem(501, "not_implemented", "Job service not configured")
    outcome, run = await service.cancel(job_id)
    if outcome == "not_found":
        raise ProblemError(404, "not_found", "Job not found")
    if outcome == "finished":
        status = run.status if run else "finished"
        return JSONResponse({"job_id": str(job_id), "status": status}, status_code=200)
    return JSONResponse({"job_id": str(job_id), "status": "cancelling"}, status_code=202)


@router.post("/v1/notify")
async def notify(request: Request, _: CoreAuth) -> Any:
    await request.body()
    return problem(501, "not_implemented", "Notify is handled by module-review")


def install_auth_handler(app: Any) -> None:
    from fastapi import Request as FRequest
    from fastapi.responses import JSONResponse as JR

    async def _unauth(_: FRequest, __: Unauthorized) -> JR:
        resp = unauthorized_response()
        if not isinstance(resp, JR):
            raise TypeError("unauthorized_response must return JSONResponse")
        return resp

    app.add_exception_handler(Unauthorized, _unauth)
