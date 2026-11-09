"""Prometheus metrics exposition (prefix publish_)."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from publish import __version__


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.build_info = Gauge(
            "publish_build_info",
            "Build information",
            ["version"],
            registry=self.registry,
        )
        self.build_info.labels(version=__version__).set(1)

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST
