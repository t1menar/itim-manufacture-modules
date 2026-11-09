"""Load module-owned secrets/settings. Values must never be logged or returned via API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from publish.db.models import ModuleSecret, ModuleSetting

SECRET_S3_ACCESS_KEY = "s3.access_key"  # noqa: S105
SECRET_S3_SECRET_KEY = "s3.secret_key"  # noqa: S105
SECRET_INSTAGRAM_DEFAULT_TOKEN = "instagram.default_access_token"  # noqa: S105

SETTING_S3 = "s3"
SETTING_INSTAGRAM_MODE = "instagram.mode"


async def get_secret(session: AsyncSession, key: str) -> str | None:
    row = await session.get(ModuleSecret, key)
    if row is None:
        return None
    value = (row.value or "").strip()
    return value or None


async def get_setting(session: AsyncSession, key: str) -> Any | None:
    row = await session.get(ModuleSetting, key)
    if row is None:
        return None
    return row.value


async def get_secrets_map(session: AsyncSession, keys: list[str]) -> dict[str, str]:
    result = await session.execute(select(ModuleSecret).where(ModuleSecret.key.in_(keys)))
    out: dict[str, str] = {}
    for row in result.scalars().all():
        val = (row.value or "").strip()
        if val:
            out[row.key] = val
    return out
