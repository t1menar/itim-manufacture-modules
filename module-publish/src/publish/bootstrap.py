"""Bootstrap configuration: the only place that reads os.environ.

Everything else is a module setting stored in Core (04 §8 / 03 §5).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

REQUIRED_VARS = (
    "PUBLISH_DATABASE_URL",
    "PUBLISH_LISTEN_ADDR",
    "MODULE_CORE_URL",
    "MODULE_CORE_TOKEN",
)

# Optional transport for module contract 2 (RabbitMQ). Absent → AMQP consumer stays off.
OPTIONAL_VARS = (
    "PUBLISH_AMQP_URL",
    "PUBLISH_AMQP_QUEUE",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
)


class ConfigError(Exception):
    """Start-up failure when bootstrap variables are missing or malformed."""


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    database_url: str = field(repr=False)
    listen_addr: str
    core_url: str
    core_token: str = field(repr=False)
    amqp_url: str | None = field(default=None, repr=False)
    amqp_queue: str = "module.publish-instagram.commands"
    otlp_endpoint: str | None = None
    otel_service_name: str = "module-publish"

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
                + ". Only bootstrap vars are read from the environment; all other "
                "configuration comes from Core settings."
            )
        listen_addr = source["PUBLISH_LISTEN_ADDR"].strip()
        host, sep, port = listen_addr.rpartition(":")
        if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
            raise ConfigError(f"PUBLISH_LISTEN_ADDR must look like host:port, got {listen_addr!r}")
        amqp = (source.get("PUBLISH_AMQP_URL") or "").strip() or None
        queue = (source.get("PUBLISH_AMQP_QUEUE") or "").strip() or "module.publish-instagram.commands"
        return cls(
            database_url=source["PUBLISH_DATABASE_URL"].strip(),
            listen_addr=listen_addr,
            core_url=source["MODULE_CORE_URL"].strip().rstrip("/"),
            core_token=source["MODULE_CORE_TOKEN"].strip(),
            amqp_url=amqp,
            amqp_queue=queue,
            otlp_endpoint=(source.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip() or None,
            otel_service_name=(source.get("OTEL_SERVICE_NAME") or "module-publish").strip() or "module-publish",
        )
