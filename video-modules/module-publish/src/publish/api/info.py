"""GET /info — module contract 1 document."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request

from publish import __version__
from publish.settings import SCHEMAS_DIR, load_settings_schema

router = APIRouter(tags=["info"])


def _load(name: str) -> dict[str, Any]:
    data = json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{name} root must be an object")
    return cast(dict[str, Any], data)


@router.get("/info")
async def info(request: Request) -> dict[str, Any]:
    config = getattr(request.app.state, "config", None)
    mode = getattr(config, "instagram_mode", "fake") if config is not None else "fake"
    if mode not in ("real", "fake"):
        mode = "fake"
    return {
        "name": f"Publish (Instagram Graph API, {mode})",
        "instagram_mode": mode,
        "version": __version__,
        "contract": 1,
        "stages": ["publish"],
        "settings_schema": load_settings_schema(),
        "input_schema": _load("input.schema.json"),
        "output_schema": _load("output.schema.json"),
        "admin_endpoints": [
            "/admin/v1/accounts",
            "/admin/v1/intents",
            "/admin/v1/secrets",
            "/admin/v1/ledger",
            "/admin/v1/dry-run",
        ],
    }


def schemas_dir() -> Path:
    return SCHEMAS_DIR
