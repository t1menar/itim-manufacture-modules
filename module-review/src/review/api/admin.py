"""Admin endpoints — secrets (write-only values), runs, stubs."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from review.api.auth import CoreAuth
from review.api.problems import problem
from review.db import secrets
from review.db.models import PendingReject, ReviewCard, Run

router = APIRouter(prefix="/admin/v1", tags=["admin"])

_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


@router.get("/secrets")
async def list_secrets(request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    async with factory() as s:
        return {"items": await secrets.list_secret_meta(s)}


@router.put("/secrets/{key}")
async def put_secret(key: str, body: SecretBody, request: Request, _: CoreAuth) -> Response:
    if not _KEY.match(key):
        return problem(422, "validation_failed", "invalid secret key")
    factory = request.app.state.session_factory
    async with factory() as s, s.begin():
        created = await secrets.upsert_secret(s, key, body.value)
    return Response(status_code=201 if created else 204)


@router.delete("/secrets/{key}", status_code=204)
async def delete_secret(key: str, request: Request, _: CoreAuth) -> Response:
    factory = request.app.state.session_factory
    async with factory() as s, s.begin():
        if not await secrets.delete_secret(s, key):
            return problem(404, "not_found", "secret not found")
    return Response(status_code=204)


@router.get("/runs")
async def list_runs(request: Request, _: CoreAuth, limit: int = 50) -> Any:
    if limit < 1 or limit > 200:
        return problem(422, "validation_failed", "limit must be 1–200")
    factory = request.app.state.session_factory
    async with factory() as s:
        rows = (await s.execute(select(Run).order_by(Run.created_at.desc()).limit(limit))).scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "job_id": str(r.job_id),
                "production_id": str(r.production_id),
                "variant_id": str(r.variant_id) if r.variant_id else None,
                "status": r.status,
                "round": r.round,
                "mode": r.mode,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "error": r.error,
            }
            for r in rows
        ]
    }


@router.get("/pending")
async def list_pending(request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    async with factory() as s:
        pending = (await s.execute(select(PendingReject))).scalars().all()
        cards = (await s.execute(select(ReviewCard).where(ReviewCard.stale.is_(False)).order_by(ReviewCard.created_at.desc()).limit(50))).scalars().all()
    return {
        "pending_rejects": [
            {
                "run_id": str(p.run_id),
                "chat_id": p.chat_id,
                "admin_user_id": p.admin_user_id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in pending
        ],
        "active_cards": [
            {
                "id": str(c.id),
                "run_id": str(c.run_id),
                "variant_id": str(c.variant_id),
                "version": c.version,
                "chat_id": c.chat_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cards
        ],
    }


@router.get("/keys")
async def list_keys(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Access keys API is phase 4+")


@router.get("/reviewers")
async def list_reviewers(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Reviewers API is phase 4+")


@router.get("/summaries")
async def list_summaries(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Summaries API is phase 7")
