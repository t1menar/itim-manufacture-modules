"""Bootstrap env for real/fake Telegram mode."""

from __future__ import annotations

from review.bootstrap import BootstrapConfig


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


def test_real_allows_missing_env_token_for_db() -> None:
    """Token may come only from module_secrets; env is optional fallback."""
    cfg = BootstrapConfig.from_env(_base(REVIEW_TELEGRAM_MODE="real"))
    assert cfg.telegram_mode == "real"
    assert cfg.telegram_bot_token is None


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
    assert "123:ABC" not in repr(cfg)
    assert cfg.reviewer_chat_ids == (9,)
