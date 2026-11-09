"""Prometheus metrics. One registry per app so tests can create many apps."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge

from mvideo import __version__


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.build_info = Gauge(
            "video_build_info", "Module build information", ["version"], registry=self.registry
        )
        self.build_info.labels(version=__version__).set(1)
