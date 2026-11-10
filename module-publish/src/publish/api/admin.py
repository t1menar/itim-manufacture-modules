"""Admin endpoints — accounts, intents, secrets (values write-only)."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from publish.api.auth import CoreAuth
from publish.api.problems import problem
from publish.db import repo, secrets
from publish.db.models import PlatformAccount, PublishIntent

router = APIRouter(prefix="/admin/v1", tags=["admin"])

_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


class AccountTokenBody(BaseModel):
    access_token: str = Field(min_length=1, max_length=8192)


def _accounts_view(accounts: list[PlatformAccount]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(a.id),
            "channel_id": a.channel_id,
            "platform": a.platform,
            "handle": a.handle,
            "external_id": a.external_id,
            "enabled": a.enabled,
            "has_token": bool((a.access_token or "").strip()),
        }
        for a in accounts
    ]


@router.get("/accounts")
async def list_accounts(request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    async with factory() as s:
        accounts = await repo.list_enabled_accounts(s)
        # also include disabled for the admin panel
        all_rows = (
            await s.execute(
                select(PlatformAccount).order_by(
                    PlatformAccount.channel_id, PlatformAccount.handle
                )
            )
        ).scalars().all()
        if all_rows:
            accounts = list(all_rows)
    return {"accounts": _accounts_view(accounts)}


@router.put("/accounts/{account_id}/token", status_code=204)
async def put_account_token(
    account_id: UUID, body: AccountTokenBody, request: Request, _: CoreAuth
) -> Response:
    factory = request.app.state.session_factory
    async with factory() as s, s.begin():
        acc = await repo.get_platform_account(s, account_id)
        if acc is None:
            return problem(404, "not_found", "account not found")
        acc.access_token = body.access_token.strip()
    return Response(status_code=204)


@router.get("/intents")
async def list_intents(request: Request, _: CoreAuth, limit: int = 50) -> Any:
    if limit < 1 or limit > 200:
        return problem(422, "validation_failed", "limit must be 1-200")
    factory = request.app.state.session_factory
    async with factory() as s:
        rows = (
            await s.execute(
                select(PublishIntent, PlatformAccount)
                .join(PlatformAccount, PlatformAccount.id == PublishIntent.platform_account_id, isouter=True)
                .order_by(PublishIntent.created_at.desc())
                .limit(limit)
            )
        ).all()
    items = []
    for intent, acc in rows:
        items.append(
            {
                "id": str(intent.id),
                "variant_id": str(intent.variant_id),
                "platform_account_id": str(intent.platform_account_id),
                "generation": intent.generation,
                "content_revision_id": str(intent.content_revision_id),
                "status": intent.status,
                "external_post_id": intent.external_post_id,
                "url": intent.url,
                "published_at": intent.published_at.isoformat() if intent.published_at else None,
                "last_error": intent.last_error,
                "created_at": intent.created_at.isoformat() if intent.created_at else None,
                "account": None
                if acc is None
                else {
                    "channel_id": acc.channel_id,
                    "platform": acc.platform,
                    "handle": acc.handle,
                    "has_token": bool((acc.access_token or "").strip()),
                },
            }
        )
    return {"items": items}


@router.get("/intents/{intent_id}")
async def get_intent(intent_id: UUID, request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    async with factory() as s:
        intent = await s.get(PublishIntent, intent_id)
        if intent is None:
            return problem(404, "not_found", "intent not found")
        acc = await s.get(PlatformAccount, intent.platform_account_id)
    return {
        "id": str(intent.id),
        "variant_id": str(intent.variant_id),
        "platform_account_id": str(intent.platform_account_id),
        "generation": intent.generation,
        "content_revision_id": str(intent.content_revision_id),
        "status": intent.status,
        "external_post_id": intent.external_post_id,
        "url": intent.url,
        "published_at": intent.published_at.isoformat() if intent.published_at else None,
        "last_error": intent.last_error,
        "created_at": intent.created_at.isoformat() if intent.created_at else None,
        "account": None
        if acc is None
        else {
            "channel_id": acc.channel_id,
            "platform": acc.platform,
            "handle": acc.handle,
            "has_token": bool((acc.access_token or "").strip()),
        },
    }


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


@router.get("/ledger")
async def list_ledger(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Publish ledger admin API is a later phase")


@router.get("/dry-run")
async def dry_run_status(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Dry-run admin API is a later phase")
