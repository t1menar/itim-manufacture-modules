"""Accounts (no secrets) and the publish ledger that prevents double posts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ID = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Account(Base):
    """Instagram business account. The access token is never stored here: a `TokenProvider` supplies it."""

    __tablename__ = "accounts"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(String(64))
    handle: Mapped[str | None] = mapped_column(String(120), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Ledger(Base):
    """One row per (account, content). `published` is terminal; `publishing` and `unknown` are never resent."""

    __tablename__ = "ledger"
    __table_args__ = (UniqueConstraint("account_code", "content_key", name="uq_ledger_content"),)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    account_code: Mapped[str] = mapped_column(String(64))
    content_key: Mapped[str] = mapped_column(String(64))
    step_key: Mapped[str] = mapped_column(String(200), index=True)
    idea_ref: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20))  # publishing | published | failed | unknown | cancelled
    caption: Mapped[str] = mapped_column(Text)
    container_id: Mapped[str | None] = mapped_column(String(64), default=None)
    external_post_id: Mapped[str | None] = mapped_column(String(64), default=None)
    url: Mapped[str | None] = mapped_column(String(500), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def as_document(self) -> dict[str, Any]:
        return {
            "status": self.status, "account": self.account_code, "container_id": self.container_id,
            "external_post_id": self.external_post_id, "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None, "error": self.error,
        }  # fmt: skip
