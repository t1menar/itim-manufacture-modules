"""Review sessions (one per gate visit) and their audit log."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ID = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Session(Base):
    """One gate visit. `step_key` is unique: a retried platform step finds its session, never a second card.

    status: pending (card sent, waiting for a tap) | awaiting_comment (rejected, waiting for the text)
          | approved | revision_requested (comment received) | escalated (round limit) | expired | cancelled
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    step_key: Mapped[str] = mapped_column(String(200), unique=True)
    idea_ref: Mapped[str] = mapped_column(String(200), index=True)
    gate: Mapped[str] = mapped_column(String(20))  # script | post
    round: Mapped[int] = mapped_column(Integer, default=1)  # 1 = first card of this idea and gate
    status: Mapped[str] = mapped_column(String(24), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, default=None)
    attempt_handle: Mapped[str | None] = mapped_column(String(300), default=None)  # SDK handle of the waiting attempt
    delivered: Mapped[bool] = mapped_column(default=False)  # the decision reached the platform
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    text: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Seen(Base):
    """Telegram update ids already processed (long polling may redeliver)."""

    __tablename__ = "seen_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
