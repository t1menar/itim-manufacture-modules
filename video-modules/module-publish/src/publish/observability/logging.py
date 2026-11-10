"""JSON structlog setup with redaction of secrets."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRET = re.compile(r"(?i)(authorization|bearer|token|api[_-]?key|password|secret|rvk_[A-Za-z0-9_-]+)")


def _redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key, value in list(event_dict.items()):
        if (_SECRET.search(str(key)) and key not in ("event", "level", "timestamp")) or (
            isinstance(value, str) and value.startswith(("mft_", "mfa_", "rvk_"))
        ):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(*, level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
