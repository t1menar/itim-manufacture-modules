"""ORM models for module-publish."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from publish.ids import uuid7

RUN_STATUSES = ("accepted", "running", "succeeded", "failed", "cancelling", "cancelled")
ACTIVE_RUN_STATUSES = ("accepted", "running", "cancelling")
Timestamp = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012
        uuid.UUID: PG_UUID(as_uuid=True),
        dict[str, Any]: JSONB,
        dt.datetime: Timestamp,
    }


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_runs_job_id"),
        CheckConstraint(
            "status in ('accepted','running','succeeded','failed','cancelling','cancelled')",
            name="ck_runs_status",
        ),
        Index(
            "ix_runs_active_status",
            "status",
            postgresql_where=text("status in ('accepted','running','cancelling')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[uuid.UUID]
    attempt: Mapped[int] = mapped_column(Integer)
    fence: Mapped[int] = mapped_column(Integer, default=1)
    production_id: Mapped[uuid.UUID]
    variant_id: Mapped[uuid.UUID | None]
    mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="accepted")
    percent: Mapped[int] = mapped_column(Integer, default=0)
    step: Mapped[str | None] = mapped_column(Text)
    settings_version: Mapped[int] = mapped_column(Integer, default=1)
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


class PlatformAccount(Base):
    """D23: platform accounts owned by module-publish."""

    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "platform",
            "handle",
            name="uq_platform_accounts_channel_platform_handle",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    channel_id: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))


class PublishIntent(Base):
    """D23: publish intents owned by module-publish (core keeps orchestration refs)."""

    __tablename__ = "publish_intents"
    __table_args__ = (
        UniqueConstraint(
            "variant_id",
            "platform_account_id",
            "generation",
            name="uq_publish_intents_variant_account_gen",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    variant_id: Mapped[uuid.UUID]
    platform_account_id: Mapped[uuid.UUID]
    generation: Mapped[int] = mapped_column(Integer)
    content_revision_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(Text, default="pending")
    external_post_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None]
    last_error: Mapped[dict[str, Any] | None]
    created_at: Mapped[dt.datetime] = mapped_column(server_default=text("now()"))
