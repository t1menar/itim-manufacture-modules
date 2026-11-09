"""Bootstrap configuration: the only thing the module reads from the environment.

Everything else (models, limits, prompts, palette, ...) arrives as a settings snapshot
with each job; the module keeps no settings of its own (03 section 6).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

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
OPTIONAL_VARS = ("OTEL_EXPORTER_OTLP_ENDPOINT",)


class ConfigError(Exception):
    """Raised at start-up when bootstrap variables are missing or malformed."""


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
        )
