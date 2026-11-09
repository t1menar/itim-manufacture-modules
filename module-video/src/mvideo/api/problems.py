"""RFC 9457 problem+json errors (04 section 1)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
TYPE_PREFIX = "urn:manufacture:problem:"


class ProblemError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str = "", **extra: Any) -> None:
        super().__init__(f"{code}: {title}")
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.extra = extra


def problem_response(status: int, code: str, title: str, detail: str = "", **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{TYPE_PREFIX}{code}",
        "title": title,
        "status": status,
        "detail": detail or title,
        "code": code,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(_: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(exc.status, exc.code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}.get(
            exc.status_code, "http_error"
        )
        return problem_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return problem_response(422, "validation_failed", "Request validation failed", errors=errors)
