"""POST /v1/jobs, GET /v1/jobs/{id}, POST /v1/jobs/{id}/cancel (04 section 2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from mvideo.api.problems import ProblemError
from mvideo.auth import require_bearer
from mvideo.intake import validate_job
from mvideo.service import JobService

router = APIRouter(dependencies=[Depends(require_bearer)])


def _service(request: Request) -> JobService:
    service: JobService | None = request.app.state.service
    if service is None:
        raise ProblemError(503, "not_ready", "Job processing is not configured")
    return service


def _job_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ProblemError(404, "not_found", "No such job") from exc


@router.post("/v1/jobs", status_code=202)
async def create_job(request: Request) -> JSONResponse:
    try:
        raw: Any = await request.json()
    except ValueError as exc:
        raise ProblemError(422, "input_invalid", "Request body is not valid JSON") from exc
    job = validate_job(raw, await _service(request).local_credentials())
    run = await _service(request).accept(job, request.headers.get("traceparent"))
    return JSONResponse({"job_id": str(run.job_id), "status": run.status}, status_code=202)


@router.get("/v1/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> JSONResponse:
    doc = await _service(request).status_document(_job_id(job_id))
    if doc is None:
        raise ProblemError(404, "not_found", "No such job")
    return JSONResponse(doc)


@router.post("/v1/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(job_id: str, request: Request) -> JSONResponse:
    jid = _job_id(job_id)
    outcome, run = await _service(request).cancel(jid)
    if outcome == "not_found" or run is None:
        raise ProblemError(404, "not_found", "No such job")
    if outcome == "finished":
        raise ProblemError(409, "job_finished", f"Job already {run.status}")
    return JSONResponse({"job_id": str(jid), "status": "cancelling"}, status_code=202)
