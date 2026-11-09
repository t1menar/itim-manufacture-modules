"""GET /info (04 section 2.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from mvideo import __version__
from mvideo.contract import input_schema, output_schema
from mvideo.settings_model import settings_schema

router = APIRouter()

ADMIN_ENDPOINTS = ["/admin/v1/runs", "/admin/v1/prompts", "/admin/v1/golden"]


def info_document() -> dict[str, Any]:
    return {
        "name": "Video (Claude Code + renderer)",
        "version": __version__,
        "contract": 1,
        "stages": ["video"],
        "settings_schema": settings_schema(),
        "input_schema": input_schema(),
        "output_schema": output_schema(),
        "admin_endpoints": ADMIN_ENDPOINTS,
    }


@router.get("/info")
async def info() -> dict[str, Any]:
    return info_document()
