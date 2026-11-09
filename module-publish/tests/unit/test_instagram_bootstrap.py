"""Bootstrap env for fake/real Instagram mode."""

from __future__ import annotations

from publish.bootstrap import BootstrapConfig


def _base(**extra: str) -> dict[str, str]:
    env = {
        "PUBLISH_DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
        "PUBLISH_LISTEN_ADDR": "127.0.0.1:8080",
        "MODULE_CORE_URL": "http://core",
        "MODULE_CORE_TOKEN": "mft_x",
    }
    env.update(extra)
    return env


def test_fake_default() -> None:
    cfg = BootstrapConfig.from_env(_base())
    assert cfg.instagram_mode == "fake"


def test_real_allows_missing_env_token_for_db() -> None:
    """Per-account platform_accounts.access_token is preferred; env optional."""
    cfg = BootstrapConfig.from_env(_base(PUBLISH_INSTAGRAM_MODE="real"))
    assert cfg.instagram_mode == "real"
    assert cfg.instagram_access_token is None


def test_real_ok() -> None:
    cfg = BootstrapConfig.from_env(
        _base(
            PUBLISH_INSTAGRAM_MODE="real",
            PUBLISH_INSTAGRAM_ACCESS_TOKEN="IGTOKEN",
            PUBLISH_INSTAGRAM_IG_USER_ID="1784",
        )
    )
    assert cfg.instagram_mode == "real"
    assert "IGTOKEN" not in repr(cfg)
