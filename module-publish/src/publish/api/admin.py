"""Admin endpoints — phase 1 stubs (501)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from publish.api.auth import CoreAuth
from publish.api.problems import problem

router = APIRouter(prefix="/admin/v1", tags=["admin"])


@router.get("/accounts")
async def list_accounts(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Accounts admin API is a later phase")


@router.get("/ledger")
async def list_ledger(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Publish ledger admin API is a later phase")


@router.get("/dry-run")
async def dry_run_status(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Dry-run admin API is a later phase")
