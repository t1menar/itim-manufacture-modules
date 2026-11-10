"""JSON logs (structlog). `production_id` goes into logs and spans, never into metric labels.

Redaction (03 section 9): keys matching `*key*`, `*token*`, `*oauth*`, `*secret*`, `*password*` and
`authorization` are masked, and the exact value of every credential registered by a run is removed
from every string, however deeply nested. The registry lives in memory only.
"""

from __future__ import annotations

import logging
import re
import sys
from collections import Counter
from typing import Any

import structlog
from opentelemetry import trace

MASK = "***"
SENSITIVE_KEY = re.compile(r"key|token|oauth|secret|password|authorization", re.I)
TOKEN_SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
_secrets: Counter[str] = Counter()  # counted: parallel runs may share one token


def register_secret(value: str) -> None:
    if len(value) >= 8:
        _secrets[value] += 1


def forget_secret(value: str) -> None:
    _secrets[value] -= 1
    if _secrets[value] <= 0:
        del _secrets[value]


def scrub_text(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, MASK)
    return TOKEN_SHAPE.sub(MASK, text)


def _scrub(value: Any, key: str = "") -> Any:
    if key and SENSITIVE_KEY.search(key) and value not in (None, "", False):
        return MASK
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v) for v in value]
    return value


def redact(_: Any, __: str, event: dict[str, Any]) -> dict[str, Any]:
    return {k: _scrub(v, k) for k, v in event.items()}


def add_fields(_: Any, __: str, event: dict[str, Any]) -> dict[str, Any]:
    event.setdefault("service", "video")
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event["trace_id"] = f"{ctx.trace_id:032x}"
        event["span_id"] = f"{ctx.span_id:016x}"
    return event


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(stream=sys.stdout, format="%(message)s", level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            add_fields,
            structlog.processors.dict_tracebacks,
            redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
