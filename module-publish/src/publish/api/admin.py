"""Admin endpoints — accounts list (D23); other stubs 501."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from publish.api.auth import CoreAuth
from publish.api.problems import problem
from publish.db import repo

router = APIRouter(prefix="/admin/v1", tags=["admin"])


@router.get("/accounts")
async def list_accounts(request: Request, _: CoreAuth) -> Any:
    factory = request.app.state.session_factory
    async with factory() as s:
        accounts = await repo.list_enabled_accounts(s)
    return {
        "accounts": [
            {
                "id": str(a.id),
                "channel_id": a.channel_id,
                "platform": a.platform,
                "handle": a.handle,
                "enabled": a.enabled,
            }
            for a in accounts
        ]
    }


@router.get("/ledger")
async def list_ledger(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Publish ledger admin API is a later phase")


@router.get("/dry-run")
async def dry_run_status(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Dry-run admin API is a later phase")
