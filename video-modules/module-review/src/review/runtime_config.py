"""Resolve runtime secrets/settings: module DB first, bootstrap env as fallback."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.bootstrap import BootstrapConfig
from review.db import secrets as secret_keys
from review.db.secrets import get_secret, get_setting


@dataclass(frozen=True, slots=True)
class RuntimeOverlay:
    """Values applied after DB load. Secrets stay repr-hidden."""

    telegram_mode: str
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_api_base: str = "https://api.telegram.org"
    admin_telegram_ids: tuple[int, ...] = ()
    chat_ids: tuple[int, ...] = ()

    @property
    def reviewer_chat_ids(self) -> tuple[int, ...]:
        return self.chat_ids or self.admin_telegram_ids


def _as_id_tuple(raw: Any) -> tuple[int, ...] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("ids") or raw.get("value")
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(int(p) for p in parts)
    if isinstance(raw, list):
        return tuple(int(x) for x in raw)
    return None


async def load_runtime_overlay(
    factory: async_sessionmaker[AsyncSession],
    config: BootstrapConfig,
) -> RuntimeOverlay:
    """DB wins when a key is present; otherwise keep bootstrap/env values."""
    async with factory() as session:
        token = await get_secret(session, secret_keys.SECRET_TELEGRAM_BOT_TOKEN)
        mode_setting = await get_setting(session, secret_keys.SETTING_TELEGRAM_MODE)
        api_base_setting = await get_setting(session, secret_keys.SETTING_TELEGRAM_API_BASE)
        admin_setting = await get_setting(session, secret_keys.SETTING_TELEGRAM_ADMIN_IDS)
        chat_setting = await get_setting(session, secret_keys.SETTING_TELEGRAM_CHAT_IDS)

    mode = config.telegram_mode
    if isinstance(mode_setting, str) and mode_setting.strip():
        mode = mode_setting.strip().lower()
    elif isinstance(mode_setting, dict) and mode_setting.get("value"):
        mode = str(mode_setting["value"]).strip().lower()

    api_base = config.telegram_api_base
    if isinstance(api_base_setting, str) and api_base_setting.strip():
        api_base = api_base_setting.strip().rstrip("/")
    elif isinstance(api_base_setting, dict) and api_base_setting.get("value"):
        api_base = str(api_base_setting["value"]).strip().rstrip("/")

    admin_ids = _as_id_tuple(admin_setting)
    chat_ids = _as_id_tuple(chat_setting)

    return RuntimeOverlay(
        telegram_mode=mode or "fake",
        telegram_bot_token=token or config.telegram_bot_token,
        telegram_api_base=api_base,
        admin_telegram_ids=admin_ids if admin_ids is not None else config.admin_telegram_ids,
        chat_ids=chat_ids if chat_ids is not None else config.chat_ids,
    )


def apply_overlay_to_bootstrap(config: BootstrapConfig, overlay: RuntimeOverlay) -> BootstrapConfig:
    """Return a new BootstrapConfig with overlay fields (for factories that still take config)."""
    return replace(
        config,
        telegram_mode=overlay.telegram_mode,
        telegram_bot_token=overlay.telegram_bot_token,
        telegram_api_base=overlay.telegram_api_base,
        admin_telegram_ids=overlay.admin_telegram_ids,
        chat_ids=overlay.chat_ids,
    )
