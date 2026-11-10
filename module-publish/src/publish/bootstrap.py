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

OPTIONAL_VARS = (
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
    "S3_SECURE",
    "S3_PUBLIC_ENDPOINT",
    "S3_PUBLIC_SECURE",
    "S3_REGION",
    "PUBLISH_AMQP_URL",
    "PUBLISH_AMQP_QUEUE",
    "PUBLISH_INSTAGRAM_MODE",  # fake | real
    "PUBLISH_INSTAGRAM_ACCESS_TOKEN",  # env fallback; prefer platform_accounts.access_token
    "PUBLISH_INSTAGRAM_IG_USER_ID",  # optional default IG user id when account.external_id empty
    "PUBLISH_INSTAGRAM_GRAPH_BASE",  # default https://graph.instagram.com
    "PUBLISH_INSTAGRAM_API_VERSION",  # default v27.0
    "PUBLISH_INSTAGRAM_UPLOAD_MODE",  # direct (file from MinIO, default) | url (public presigned link)
    "PUBLISH_INSTAGRAM_UPLOAD_BASE",  # default https://rupload.facebook.com
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
    instagram_mode: str = "fake"
    instagram_access_token: str | None = field(default=None, repr=False)
    instagram_ig_user_id: str | None = None
    instagram_graph_base: str = "https://graph.instagram.com"
    instagram_api_version: str = "v27.0"
    instagram_upload_mode: str = "direct"
    instagram_upload_base: str = "https://rupload.facebook.com"

    s3_env_fallback: dict[str, str] = field(default_factory=dict, repr=False)

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
        mode = (source.get("PUBLISH_INSTAGRAM_MODE") or "fake").strip().lower() or "fake"
        if mode not in {"fake", "real"}:
            raise ConfigError("PUBLISH_INSTAGRAM_MODE must be 'fake' or 'real'")
        # Token: prefer platform_accounts.access_token / module_secrets; env is fallback.
        token = (source.get("PUBLISH_INSTAGRAM_ACCESS_TOKEN") or "").strip() or None

        s3_keys = (
            "S3_ENDPOINT",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "S3_BUCKET",
            "S3_SECURE",
            "S3_PUBLIC_ENDPOINT",
            "S3_PUBLIC_SECURE",
            "S3_REGION",
        )
        s3_env = {k: source[k].strip() for k in s3_keys if (source.get(k) or "").strip()}
        return cls(
            database_url=source["PUBLISH_DATABASE_URL"].strip(),
            listen_addr=listen_addr,
            core_url=source["MODULE_CORE_URL"].strip().rstrip("/"),
            core_token=source["MODULE_CORE_TOKEN"].strip(),
            amqp_url=amqp,
            amqp_queue=queue,
            otlp_endpoint=(source.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip() or None,
            otel_service_name=(source.get("OTEL_SERVICE_NAME") or "module-publish").strip()
            or "module-publish",
            instagram_mode=mode,
            instagram_access_token=token,
            instagram_ig_user_id=(source.get("PUBLISH_INSTAGRAM_IG_USER_ID") or "").strip() or None,
            instagram_graph_base=(source.get("PUBLISH_INSTAGRAM_GRAPH_BASE") or "https://graph.instagram.com")
            .strip()
            .rstrip("/"),
            instagram_api_version=(source.get("PUBLISH_INSTAGRAM_API_VERSION") or "v27.0").strip() or "v27.0",
            instagram_upload_mode=(source.get("PUBLISH_INSTAGRAM_UPLOAD_MODE") or "direct").strip().lower()
            or "direct",
            instagram_upload_base=(
                source.get("PUBLISH_INSTAGRAM_UPLOAD_BASE") or "https://rupload.facebook.com"
            )
            .strip()
            .rstrip("/"),
            s3_env_fallback=s3_env,
        )
