"""Spans of 03 section 8 (needs the OpenTelemetry SDK; skipped without it)."""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.config import BootstrapConfig
from mvideo.storage import Storage
from tests.harness import Harness, build_harness


async def test_a_job_produces_the_spans_with_production_id_and_the_core_trace(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    harness: Harness = build_harness(engine, storage, config)
    body = await harness.submit()
    await harness.run_all()
    spans = exporter.get_finished_spans()
    names = {s.name for s in spans}
    assert {"video.job", "step.analysis", "step.package", "core.callback", "s3.upload"} <= names
    assert all(
        s.attributes.get("production_id") == body["production_id"] for s in spans if s.name == "video.job"
    )


def test_job_span_continues_the_traceparent() -> None:
    from mvideo.observability.tracing import job_span

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with job_span(tp, "prod-1"):
        pass
    (sp,) = exporter.get_finished_spans()
    assert f"{sp.context.trace_id:032x}" == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert sp.parent is not None and sp.attributes["production_id"] == "prod-1"
