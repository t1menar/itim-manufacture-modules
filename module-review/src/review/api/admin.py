"""Admin endpoints — phase 1 stubs (501)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from review.api.auth import CoreAuth
from review.api.problems import problem

router = APIRouter(prefix="/admin/v1", tags=["admin"])


@router.get("/keys")
async def list_keys(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Access keys API is phase 4+")


@router.get("/reviewers")
async def list_reviewers(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Reviewers API is phase 4+")


@router.get("/summaries")
async def list_summaries(_: CoreAuth) -> Any:
    return problem(501, "not_implemented", "Summaries API is phase 7")
