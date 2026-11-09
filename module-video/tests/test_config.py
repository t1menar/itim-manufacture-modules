from __future__ import annotations

import pytest

from mvideo.config import REQUIRED_VARS, BootstrapConfig, ConfigError


def test_reads_bootstrap_variables(env: dict[str, str]) -> None:
    cfg = BootstrapConfig.from_env(env)
    assert cfg.core_url == "http://core:8080"  # trailing slash removed
    assert (cfg.host, cfg.port) == ("0.0.0.0", 8080)
    assert cfg.otlp_endpoint is None


def test_missing_variables_are_all_reported_at_once(env: dict[str, str]) -> None:
    del env["MODULE_CORE_TOKEN"]
    del env["S3_BUCKET"]
    with pytest.raises(ConfigError) as err:
        BootstrapConfig.from_env(env)
    assert "MODULE_CORE_TOKEN" in str(err.value)
    assert "S3_BUCKET" in str(err.value)


@pytest.mark.parametrize("name", REQUIRED_VARS)
def test_every_required_variable_is_enforced(env: dict[str, str], name: str) -> None:
    env[name] = "  "
    with pytest.raises(ConfigError, match=name):
        BootstrapConfig.from_env(env)


@pytest.mark.parametrize("bad", ["8080", "host:", ":8080", "host:99999", "host:http"])
def test_listen_addr_must_be_host_port(env: dict[str, str], bad: str) -> None:
    env["VIDEO_LISTEN_ADDR"] = bad
    with pytest.raises(ConfigError, match="VIDEO_LISTEN_ADDR"):
        BootstrapConfig.from_env(env)


def test_secrets_are_not_in_repr(config: BootstrapConfig) -> None:
    text = repr(config)
    for secret in ("test-token", "secret", "pw@"):
        assert secret not in text
