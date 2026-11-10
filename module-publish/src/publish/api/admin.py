"""Admin endpoints — accounts, intents, secrets (values write-only)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from publish.api.auth import CoreAuth
from publish.api.problems import problem
from publish.db import repo, secrets
from publish.db.models import PlatformAccount, PublishIntent
from publish.ids import uuid7
from publish.observability.logging import get_logger

router = APIRouter(prefix="/admin/v1", tags=["admin"])

log = get_logger("publish.admin")

_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


class AccountTokenBody(BaseModel):
    access_token: str = Field(min_length=1, max_length=8192)


class AccountCreateBody(BaseModel):
    channel_id: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=64)
    handle: str | None = Field(default=None, max_length=128)
    external_id: str | None = Field(default=None, max_length=256)
    enabled: bool = True
    access_token: str | None = Field(default=None, min_length=1, max_length=8192)


class AccountUpdateBody(BaseModel):
    channel_id: str | None = Field(default=None, min_length=1, max_length=64)
    platform: str | None = Field(default=None, min_length=1, max_length=64)
    handle: str | None = Field(default=None, max_length=128)
    external_id: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None
    access_token: str | None = Field(default=None, min_length=1, max_length=8192)


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
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
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
            (
                await s.execute(
                    select(PlatformAccount).order_by(PlatformAccount.channel_id, PlatformAccount.handle)
                )
            )
            .scalars()
            .all()
        )
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
        acc.updated_at = datetime.now(UTC)
    actor = request.headers.get("x-actor") or request.headers.get("x-admin-actor") or "admin"
    log.info("account_token_written", account_id=str(account_id), actor=actor)
    return Response(status_code=204)


def _apply_account_fields(acc: PlatformAccount, body: AccountUpdateBody | AccountCreateBody) -> None:
    if body.channel_id is not None:
        acc.channel_id = body.channel_id.strip()
    if body.platform is not None:
        acc.platform = body.platform.strip().lower()
    if body.handle is not None:
        acc.handle = body.handle.strip() or None
    if body.external_id is not None:
        acc.external_id = body.external_id.strip() or None
    if body.enabled is not None:
        acc.enabled = body.enabled
    if body.access_token is not None:
        acc.access_token = body.access_token.strip()
    acc.updated_at = datetime.now(UTC)


@router.post("/accounts", status_code=201)
async def create_account(body: AccountCreateBody, request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    now = datetime.now(UTC)
    acc = PlatformAccount(
        id=uuid7(),
        channel_id=body.channel_id.strip(),
        platform=body.platform.strip().lower(),
        handle=(body.handle or "").strip() or None,
        external_id=(body.external_id or "").strip() or None,
        enabled=body.enabled,
        access_token=body.access_token.strip() if body.access_token else None,
        updated_at=now,
        created_at=now,
    )
    try:
        async with factory() as s, s.begin():
            s.add(acc)
            await s.flush()
            view = _accounts_view([acc])[0]
    except IntegrityError:
        return problem(409, "conflict", "account with this channel, platform and handle already exists")
    actor = request.headers.get("x-actor") or request.headers.get("x-admin-actor") or "admin"
    log.info("account_created", account_id=str(acc.id), actor=actor, has_token=bool(body.access_token))
    return view


@router.patch("/accounts/{account_id}")
async def patch_account(account_id: UUID, body: AccountUpdateBody, request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    try:
        async with factory() as s, s.begin():
            acc = await repo.get_platform_account(s, account_id)
            if acc is None:
                return problem(404, "not_found", "account not found")
            _apply_account_fields(acc, body)
            await s.flush()
            view = _accounts_view([acc])[0]
    except IntegrityError:
        return problem(409, "conflict", "account with this channel, platform and handle already exists")
    actor = request.headers.get("x-actor") or request.headers.get("x-admin-actor") or "admin"
    log.info(
        "account_updated",
        account_id=str(account_id),
        actor=actor,
        token_updated=body.access_token is not None,
    )
    return view


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
    actor = request.headers.get("x-actor") or request.headers.get("x-admin-actor") or "admin"
    log.info("secret_upserted", key=key, actor=actor, created=created)
    return Response(status_code=201 if created else 204)


@router.delete("/secrets/{key}", status_code=204)
async def delete_secret(key: str, request: Request, _: CoreAuth) -> Response:
    factory = request.app.state.session_factory
    async with factory() as s, s.begin():
        if not await secrets.delete_secret(s, key):
            return problem(404, "not_found", "secret not found")
    actor = request.headers.get("x-actor") or request.headers.get("x-admin-actor") or "admin"
    log.info("secret_deleted", key=key, actor=actor)
    return Response(status_code=204)


@router.get("/ledger")
async def list_ledger(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Publish ledger admin API is a later phase")


@router.get("/dry-run")
async def dry_run_status(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Dry-run admin API is a later phase")
