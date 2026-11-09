"""Load module-owned secrets/settings. Values must never be logged or returned via API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from review.db.models import ModuleSecret, ModuleSetting

# Well-known keys (documented in README).
SECRET_TELEGRAM_BOT_TOKEN = "telegram.bot_token"  # noqa: S105
SECRET_S3_ACCESS_KEY = "s3.access_key"  # noqa: S105
SECRET_S3_SECRET_KEY = "s3.secret_key"  # noqa: S105

SETTING_TELEGRAM_MODE = "telegram.mode"
SETTING_TELEGRAM_API_BASE = "telegram.api_base"
SETTING_TELEGRAM_ADMIN_IDS = "telegram.admin_ids"
SETTING_TELEGRAM_CHAT_IDS = "telegram.chat_ids"
SETTING_S3 = "s3"


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
