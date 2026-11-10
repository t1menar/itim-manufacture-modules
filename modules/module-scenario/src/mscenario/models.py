"""Tables: the knowledge cache and stored results (Postgres in production, SQLite in unit tests)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BigId = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class KnowledgeFact(Base):
    """A verified fact about a system at a commit, reusable by every later idea on the same system."""

    __tablename__ = "knowledge_facts"
    __table_args__ = (UniqueConstraint("system", "commit", "key"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    system: Mapped[str] = mapped_column(Text, index=True)  # normalized repository URL
    commit: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(String(64))  # sha256 of the normalized citation
    text: Mapped[str] = mapped_column(Text)
    cite: Mapped[dict[str, Any]] = mapped_column(JSON)
    kind: Mapped[str] = mapped_column(String(8))  # code | url
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchResult(Base):
    """Result per platform step key: a retried step returns the stored document instead of paying again."""

    __tablename__ = "research_results"

    step_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    idea_ref: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # done | blocked
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal(0))
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScriptResult(Base):
    """Result per platform step key; one row per review round (`visit`) so earlier rounds stay for audit."""

    __tablename__ = "script_results"

    step_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    idea_ref: Mapped[str] = mapped_column(String(64), index=True)
    visit: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))  # done | blocked
    document: Mapped[dict[str, Any]] = mapped_column(JSON)  # {"script": ..., "post": ...} or the blocked reason
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal(0))
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
