from __future__ import annotations

import ast
from pathlib import Path

import pytest

from publish.bootstrap import BootstrapConfig, ConfigError


def test_from_env_requires_four_vars() -> None:
    with pytest.raises(ConfigError, match="PUBLISH_DATABASE_URL"):
        BootstrapConfig.from_env({})


def test_from_env_ok() -> None:
    cfg = BootstrapConfig.from_env(
        {
            "PUBLISH_DATABASE_URL": "postgresql+asyncpg://u:p@h/db",
            "PUBLISH_LISTEN_ADDR": "0.0.0.0:8080",
            "MODULE_CORE_URL": "http://core:8080/",
            "MODULE_CORE_TOKEN": "secret",
        }
    )
    assert cfg.port == 8080
    assert cfg.core_url == "http://core:8080"
    assert "secret" not in repr(cfg)


def test_only_bootstrap_reads_os_environ() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "publish"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr == "environ"
                and path.name != "bootstrap.py"
            ):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
