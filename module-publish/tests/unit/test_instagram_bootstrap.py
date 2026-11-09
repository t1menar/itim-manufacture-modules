"""Bootstrap env for fake/real Instagram mode."""

from __future__ import annotations

import pytest

from publish.bootstrap import BootstrapConfig, ConfigError


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


def test_real_requires_token() -> None:
    with pytest.raises(ConfigError, match="ACCESS_TOKEN"):
        BootstrapConfig.from_env(_base(PUBLISH_INSTAGRAM_MODE="real"))


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
