"""OpenTelemetry spans (03 section 8). The API is always importable and does nothing without the SDK;
`setup_tracing` installs an OTLP exporter when the SDK is present and an endpoint is configured.

Spans: `video.job` (continues the core's `traceparent`), one per step, `agent.run`, `sandbox.exec`,
`render.chunk`, `s3.upload`, `core.callback`. `production_id` is an attribute of every span.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_production: ContextVar[str | None] = ContextVar("mvideo_production_id", default=None)
_propagator = TraceContextTextMapPropagator()


def setup_tracing(otlp_endpoint: str | None, *, service: str = "video") -> bool:
    """Returns True when an exporter was installed."""
    if not otlp_endpoint:
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)
    return True


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """A child span of the current one; `production_id` is added from the run being executed."""
    tracer = trace.get_tracer("mvideo")
    with tracer.start_as_current_span(name) as sp:
        production = _production.get()
        if production:
            sp.set_attribute("production_id", production)
        for key, value in attributes.items():
            if value is not None:
                sp.set_attribute(key, value)
        yield sp


@contextlib.contextmanager
def job_span(traceparent: str | None, production_id: str, **attributes: Any) -> Iterator[trace.Span]:
    """Root span `video.job`, continuing the trace of the core when a `traceparent` came with the job."""
    parent = _propagator.extract({"traceparent": traceparent}) if traceparent else None
    token = otel_context.attach(parent) if parent is not None else None
    prod_token = _production.set(production_id)
    try:
        with span("video.job", **attributes) as sp:
            yield sp
    finally:
        _production.reset(prod_token)
        if token is not None:
            otel_context.detach(token)
