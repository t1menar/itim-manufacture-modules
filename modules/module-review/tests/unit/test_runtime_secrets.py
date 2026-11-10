"""DB-first secret overlay (uses FakeTelegram / in-memory style via mocks)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from review.bootstrap import BootstrapConfig
from review.db import secrets as keys
from review.runtime_config import apply_overlay_to_bootstrap, load_runtime_overlay


def _cfg(**kw: Any) -> BootstrapConfig:
    base = BootstrapConfig(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        listen_addr="127.0.0.1:8080",
        core_url="http://core",
        core_token="mft_x",
        telegram_mode="fake",
        telegram_bot_token=None,
        admin_telegram_ids=(1,),
        chat_ids=(),
    )
    return replace(base, **kw) if kw else base


@pytest.mark.asyncio
async def test_overlay_prefers_db_token() -> None:
    session = AsyncMock()
    session.get = AsyncMock(
        side_effect=lambda model, key: {
            keys.SECRET_TELEGRAM_BOT_TOKEN: MagicMock(value="db-token:1"),
            keys.SETTING_TELEGRAM_MODE: MagicMock(value="real"),
            keys.SETTING_TELEGRAM_API_BASE: MagicMock(value="https://api.telegram.org"),
            keys.SETTING_TELEGRAM_ADMIN_IDS: MagicMock(value={"ids": [10, 20]}),
            keys.SETTING_TELEGRAM_CHAT_IDS: MagicMock(value={"ids": [99]}),
        }.get(key)
    )
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx

    overlay = await load_runtime_overlay(factory, _cfg(telegram_bot_token="env-token"))
    assert overlay.telegram_bot_token == "db-token:1"
    assert overlay.telegram_mode == "real"
    assert overlay.admin_telegram_ids == (10, 20)
    assert overlay.reviewer_chat_ids == (99,)
    effective = apply_overlay_to_bootstrap(_cfg(), overlay)
    assert "db-token" not in repr(effective)
