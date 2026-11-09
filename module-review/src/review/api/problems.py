"""RFC 9457 problem+json helpers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        *,
        detail: str | None = None,
        errors: list[Any] | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors


def problem(
    status: int,
    code: str,
    title: str,
    *,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:manufacture:problem:{code}",
        "title": title,
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def problem_exc(_: Request, exc: ProblemError) -> JSONResponse:
        extra: dict[str, Any] = {}
        if exc.errors is not None:
            extra["errors"] = exc.errors
        return problem(exc.status, exc.code, exc.title, detail=exc.detail, extra=extra or None)

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        title = str(exc.detail) if exc.detail else "HTTP error"
        if exc.status_code == 404:
            title = "Not found"
            code = "not_found"
        return problem(exc.status_code, code, title)

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(422, "validation_failed", "Request validation failed", detail=str(exc.errors()))
