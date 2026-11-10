"""Tables: one stored result per platform step (idempotency) and the capture cache."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class GenerationResult(Base):
    """Output of one generation step. A retried step returns this row and spends nothing."""

    __tablename__ = "generation_results"

    step_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    idea_ref: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20))  # done | failed
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CaptureCache(Base):
    """A recorded capture keyed by the sha256 of (plan, script commands, image): reused by revisions."""

    __tablename__ = "capture_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    capture: Mapped[dict[str, Any]] = mapped_column(JSON)
    log: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
