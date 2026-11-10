"""HTTP API (`/v1`): where the owner enters and organises ideas. Loopback or a bearer token only."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from midea import schemas
from midea.db import transaction
from midea.service import Conflict, IdeaService, NotFound, NotReady, TransitionError
from midea.status import IdeaStatus


async def get_service(request: Request) -> AsyncIterator[IdeaService]:
    sm: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with transaction(sm) as session:
        yield IdeaService(session)


Svc = Annotated[IdeaService, Depends(get_service)]


def require_token(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    token: str | None = request.app.state.api_token
    if not token:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, token):
        raise HTTPException(401, "invalid or missing bearer token")


router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])


@router.put("/environments", response_model=schemas.EnvironmentOut)
async def put_environment(body: schemas.EnvironmentIn, svc: Svc) -> Any:
    return await svc.upsert_environment(body)


@router.put("/rubrics", response_model=schemas.RubricOut)
async def put_rubric(body: schemas.RubricIn, svc: Svc) -> Any:
    return await svc.upsert_rubric(body)


@router.post("/playlists", response_model=schemas.PlaylistOut, status_code=201)
async def create_playlist(body: schemas.PlaylistIn, svc: Svc) -> Any:
    return await svc.create_playlist(body)


@router.get("/playlists", response_model=list[schemas.PlaylistOut])
async def list_playlists(svc: Svc, status: str | None = None) -> Any:
    return await svc.list_playlists(status)


@router.get("/playlists/{code}", response_model=schemas.PlaylistDetail)
async def get_playlist(code: str, svc: Svc) -> Any:
    pl = await svc.playlist_by_code(code)
    out = schemas.PlaylistDetail.model_validate(pl)
    out.idea_ids = await svc.playlist_idea_ids(pl.id)
    return out


@router.patch("/playlists/{code}", response_model=schemas.PlaylistOut)
async def patch_playlist(code: str, body: schemas.PlaylistPatch, svc: Svc) -> Any:
    return await svc.update_playlist(code, body)


@router.post("/playlists/{code}/ideas", status_code=204)
async def playlist_add(code: str, body: schemas.PlaylistAdd, svc: Svc) -> None:
    await svc.add_to_playlist(code, body.idea_id, body.position)


@router.delete("/playlists/{code}/ideas/{idea_id}", status_code=204)
async def playlist_remove(code: str, idea_id: int, svc: Svc) -> None:
    await svc.remove_from_playlist(code, idea_id)


@router.put("/playlists/{code}/order", status_code=204)
async def playlist_order(code: str, body: schemas.PlaylistOrder, svc: Svc) -> None:
    await svc.reorder_playlist(code, body.idea_ids)


@router.post("/ideas", response_model=schemas.IdeaOut, status_code=201)
async def create_idea(body: schemas.IdeaIn, svc: Svc) -> Any:
    return await svc.create_idea(body)


@router.get("/ideas", response_model=list[schemas.IdeaOut])
async def list_ideas(
    svc: Svc,
    status: str | None = None,
    playlist: str | None = None,
    rubric: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    return await svc.list_ideas(
        status=status, playlist_code=playlist, rubric_code=rubric, limit=min(limit, 500), offset=offset
    )


@router.get("/ideas/{idea_id}", response_model=schemas.IdeaOut)
async def get_idea(idea_id: int, svc: Svc) -> Any:
    return await svc.get_idea(idea_id)


@router.patch("/ideas/{idea_id}", response_model=schemas.IdeaOut)
async def patch_idea(idea_id: int, body: schemas.IdeaPatch, svc: Svc) -> Any:
    return await svc.update_idea(idea_id, body)


@router.delete("/ideas/{idea_id}", status_code=204)
async def delete_idea(idea_id: int, svc: Svc) -> None:
    await svc.delete_idea(idea_id)


@router.post("/ideas/{idea_id}/status", response_model=schemas.IdeaOut)
async def change_status(idea_id: int, body: schemas.StatusChange, svc: Svc) -> Any:
    return await svc.set_status(idea_id, IdeaStatus(body.status), note=body.note)


@router.get("/ideas/{idea_id}/document")
async def idea_document(idea_id: int, svc: Svc, rev: int | None = None) -> dict[str, Any]:
    idea = await svc.get_idea(idea_id)
    return await svc.revision_document(idea_id, rev or idea.rev)


@router.post("/ideas/{idea_id}/outcomes", response_model=schemas.OutcomeOut, status_code=201)
async def add_outcome(idea_id: int, body: schemas.OutcomeIn, svc: Svc) -> Any:
    return await svc.add_outcome(idea_id, body)


@router.get("/stats", response_model=list[schemas.GroupStat])
async def stats(svc: Svc, group_by: str = "rubric") -> Any:
    try:
        return await svc.stats(group_by)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


def register_errors(app: FastAPI) -> None:
    def problem(status: int, title: str, detail: str, extra: dict[str, Any] | None = None) -> JSONResponse:
        body = {"type": "about:blank", "title": title, "status": status, "detail": detail, **(extra or {})}
        return JSONResponse(body, status_code=status, media_type="application/problem+json")

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound) -> JSONResponse:
        return problem(404, "not found", str(e))

    @app.exception_handler(Conflict)
    async def _cf(_: Request, e: Conflict) -> JSONResponse:
        return problem(409, "conflict", str(e))

    @app.exception_handler(TransitionError)
    async def _te(_: Request, e: TransitionError) -> JSONResponse:
        return problem(409, "invalid status change", str(e))

    @app.exception_handler(NotReady)
    async def _nr(_: Request, e: NotReady) -> JSONResponse:
        return problem(422, "idea is not ready", str(e), {"issues": e.issues})
