"""Bootstrap configuration: the only thing the module reads from the environment.

Everything else (models, limits, prompts, palette, ...) arrives as a settings snapshot
with each job; the module keeps no settings of its own (03 section 6).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

REQUIRED_VARS = (
    "VIDEO_DATABASE_URL",
    "VIDEO_LISTEN_ADDR",
    "MODULE_CORE_URL",
    "MODULE_CORE_TOKEN",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "DOCKER_HOST",
    "VIDEO_AGENT_NETWORK",
)
OPTIONAL_VARS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "MODULE_AMQP_URL",  # without it the idea scheduler, relay and status consumer stay off
    "MODULE_AMQP_PREFIX",
    "MODULE_ID",  # id in the core registry: names the command queue (default video-claude)
    "VIDEO_IDEAS_TICK_S",
    "VIDEO_IDEAS_MAX_DISPATCH",
    "VIDEO_IDEAS_MAX_IN_FLIGHT",
    "VIDEO_IDEAS_PAUSED",
    "VIDEO_IDEAS_INTERVAL_S",  # at least this many seconds between two dispatched ideas (0 = no spacing)
)


class ConfigError(Exception):
    """Raised at start-up when bootstrap variables are missing or malformed."""


def _number(source: Mapping[str, str], name: str, default: float, kind: type) -> Any:
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    # Secrets and URLs with credentials are kept out of repr() so they never reach logs.
    database_url: str = field(repr=False)
    listen_addr: str
    core_url: str
    core_token: str = field(repr=False)
    s3_endpoint: str
    s3_access_key: str = field(repr=False)
    s3_secret_key: str = field(repr=False)
    s3_bucket: str
    docker_host: str
    agent_network: str
    otlp_endpoint: str | None = None
    amqp_url: str | None = field(default=None, repr=False)
    amqp_prefix: str = ""
    module_id: str = "video-claude"
    ideas_tick_s: float = 5.0
    ideas_max_dispatch: int = 5
    ideas_max_in_flight: int = 3
    ideas_paused: bool = False
    ideas_interval_s: float = 0.0

    @property
    def host(self) -> str:
        return self.listen_addr.rpartition(":")[0]

    @property
    def port(self) -> int:
        return int(self.listen_addr.rpartition(":")[2])

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BootstrapConfig:
        source = os.environ if env is None else env
        missing = [name for name in REQUIRED_VARS if not source.get(name, "").strip()]
        if missing:
            raise ConfigError(
                "missing required environment variables: "
                + ", ".join(missing)
                + ". The module reads only these bootstrap variables; all other "
                "configuration comes from job settings."
            )
        listen_addr = source["VIDEO_LISTEN_ADDR"].strip()
        host, sep, port = listen_addr.rpartition(":")
        if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
            raise ConfigError(f"VIDEO_LISTEN_ADDR must look like host:port, got {listen_addr!r}")
        return cls(
            database_url=source["VIDEO_DATABASE_URL"].strip(),
            listen_addr=listen_addr,
            core_url=source["MODULE_CORE_URL"].strip().rstrip("/"),
            core_token=source["MODULE_CORE_TOKEN"].strip(),
            s3_endpoint=source["S3_ENDPOINT"].strip(),
            s3_access_key=source["S3_ACCESS_KEY"].strip(),
            s3_secret_key=source["S3_SECRET_KEY"].strip(),
            s3_bucket=source["S3_BUCKET"].strip(),
            docker_host=source["DOCKER_HOST"].strip(),
            agent_network=source["VIDEO_AGENT_NETWORK"].strip(),
            otlp_endpoint=(source.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip() or None,
            amqp_url=(source.get("MODULE_AMQP_URL") or "").strip() or None,
            amqp_prefix=(source.get("MODULE_AMQP_PREFIX") or "").strip(),
            module_id=(source.get("MODULE_ID") or "").strip() or "video-claude",
            ideas_tick_s=_number(source, "VIDEO_IDEAS_TICK_S", 5.0, float),
            ideas_max_dispatch=_number(source, "VIDEO_IDEAS_MAX_DISPATCH", 5, int),
            ideas_max_in_flight=_number(source, "VIDEO_IDEAS_MAX_IN_FLIGHT", 3, int),
            ideas_interval_s=_number(source, "VIDEO_IDEAS_INTERVAL_S", 0.0, float),
            ideas_paused=(source.get("VIDEO_IDEAS_PAUSED") or "").strip().lower() in ("1", "true", "yes"),
        )
