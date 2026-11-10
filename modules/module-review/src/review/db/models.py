from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import BigInteger, Boolean, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from review.ids import uuid7

Timestamp = TIMESTAMP(timezone=True)
ACTIVE = ("accepted", "running", "awaiting_decision", "awaiting_reason", "cancelling")
FINAL = frozenset({"succeeded", "failed", "cancelled"})


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012
        uuid.UUID: PG_UUID(as_uuid=True),
        dict[str, Any]: JSONB,
        dt.datetime: Timestamp,
    }


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("job_id", name="uq_review_runs_job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[uuid.UUID]
    attempt: Mapped[int] = mapped_column(Integer)
    fence: Mapped[int] = mapped_column(Integer, default=1)
    production_id: Mapped[uuid.UUID]
    variant_id: Mapped[uuid.UUID | None]
    mode: Mapped[str] = mapped_column(Text)
    round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(Text, default="accepted")
    percent: Mapped[int] = mapped_column(Integer, default=0)
    step: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]]
    input: Mapped[dict[str, Any]]
    deadline: Mapped[dt.datetime]
    callback_base_url: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None]
    error: Mapped[dict[str, Any] | None]
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[dt.datetime | None]
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    started_at: Mapped[dt.datetime | None]
    finished_at: Mapped[dt.datetime | None]


class ReviewCard(Base):
    __tablename__ = "review_cards"
    __table_args__ = (UniqueConstraint("variant_id", "version", name="uq_cards_variant_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[uuid.UUID]
    variant_id: Mapped[uuid.UUID]
    version: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(Integer)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class PendingReject(Base):
    __tablename__ = "pending_reject"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    admin_user_id: Mapped[int] = mapped_column(BigInteger)
    card_message_id: Mapped[int | None] = mapped_column(Integer)
    asked_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class ModuleSecret(Base):
    """Secret key/value owned by module-review (never log or return via API)."""

    __tablename__ = "module_secrets"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class ModuleSetting(Base):
    """Non-secret JSON settings (admin ids, chat ids, S3 endpoints, modes)."""

    __tablename__ = "module_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
