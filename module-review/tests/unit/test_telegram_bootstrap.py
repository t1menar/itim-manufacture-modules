"""Bootstrap env for real/fake Telegram mode."""

from __future__ import annotations

import pytest

from review.bootstrap import BootstrapConfig, ConfigError


def _base(**extra: str) -> dict[str, str]:
    env = {
        "REVIEW_DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
        "REVIEW_LISTEN_ADDR": "127.0.0.1:8080",
        "MODULE_CORE_URL": "http://core",
        "MODULE_CORE_TOKEN": "mft_x",
    }
    env.update(extra)
    return env


def test_fake_default() -> None:
    cfg = BootstrapConfig.from_env(_base())
    assert cfg.telegram_mode == "fake"
    assert cfg.telegram_bot_token is None


def test_real_requires_token() -> None:
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        BootstrapConfig.from_env(_base(REVIEW_TELEGRAM_MODE="real"))


def test_real_ok() -> None:
    cfg = BootstrapConfig.from_env(
        _base(
            REVIEW_TELEGRAM_MODE="real",
            REVIEW_TELEGRAM_BOT_TOKEN="123:ABC",
            REVIEW_ADMIN_TELEGRAM_IDS="1,2",
            REVIEW_CHAT_IDS="9",
        )
    )
    assert cfg.telegram_mode == "real"
    assert cfg.telegram_bot_token == "123:ABC"
    assert "token" not in repr(cfg).lower() or "***" in repr(cfg) or "123:ABC" not in repr(cfg)
    assert cfg.reviewer_chat_ids == (9,)
