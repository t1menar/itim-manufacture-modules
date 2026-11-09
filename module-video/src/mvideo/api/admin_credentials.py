"""`/admin/v1/credentials`: secrets kept in the module database. Values are write-only."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, ValidationError

from mvideo.api.problems import ProblemError
from mvideo.auth import require_bearer
from mvideo.db import credentials_repo as repo
from mvideo.db.engine import session_factory

router = APIRouter(prefix="/admin/v1/credentials", dependencies=[Depends(require_bearer)])

KINDS = ("claude_oauth_token", "anthropic_api_key")
REF = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class NewCredential(BaseModel):
    kind: str
    value: Annotated[str, Field(min_length=8, max_length=4096)]
    note: Annotated[str | None, Field(max_length=500)] = None


def _factory(request: Request) -> Any:
    engine = request.app.state.engine
    if engine is None:
        raise ProblemError(503, "not_ready", "No database is configured")
    return session_factory(engine)


@router.get("")
async def list_credentials(request: Request) -> list[dict[str, Any]]:
    async with _factory(request)() as s:
        return await repo.list_meta(s)


@router.put("/{ref}")
async def put_credential(ref: str, request: Request) -> Response:
    try:
        body = NewCredential.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        raise ProblemError(422, "input_invalid", "Request body is invalid (the value is not echoed)") from exc
    if not REF.match(ref):
        raise ProblemError(422, "input_invalid", "ref must be CAPITAL_SNAKE_CASE, e.g. CLAUDE_OAUTH_TOKEN")
    if body.kind not in KINDS:
        raise ProblemError(422, "input_invalid", f"kind must be one of {', '.join(KINDS)}")
    actor = request.headers.get("x-actor", "admin")[:100]
    async with _factory(request)() as s, s.begin():
        created = await repo.put(s, ref, body.kind, body.value.strip(), note=body.note, actor=actor)
    return Response(status_code=201 if created else 204)


@router.delete("/{ref}", status_code=204)
async def delete_credential(ref: str, request: Request) -> Response:
    async with _factory(request)() as s, s.begin():
        if not await repo.delete_one(s, ref):
            raise ProblemError(404, "not_found", "No such credential")
    return Response(status_code=204)
