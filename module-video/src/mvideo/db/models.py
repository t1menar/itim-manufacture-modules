"""Tables of database `video` (03 section 7).

Constraints that idempotency and recovery depend on (unique job_id, unique step per try, status
enums, cascades) live in the schema, not only in code (05 section 8).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mvideo.ids import uuid7

RUN_STATUSES = ("accepted", "running", "succeeded", "failed", "cancelling", "cancelled")
ACTIVE_RUN_STATUSES = ("accepted", "running", "cancelling")
STEP_STATUSES = ("pending", "running", "succeeded", "reused", "blocked", "failed", "skipped")
CHECK_STATUSES = ("pass", "warn", "fail")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in ({', '.join(repr(v) for v in values)})"


Timestamp = TIMESTAMP(timezone=True)
Cost = Numeric(10, 4)


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012
        uuid.UUID: PG_UUID(as_uuid=True),
        dict[str, Any]: JSONB,
        dt.datetime: Timestamp,
    }


def _now_default() -> Any:
    return text("now()")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_runs_job_id"),
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_runs_status"),
        CheckConstraint(_in("mode", ("create", "revise")), name="ck_runs_mode"),
        Index("ix_runs_production_created", "production_id", text("created_at DESC")),
        Index(
            "ix_runs_active_status",
            "status",
            postgresql_where=text(_in("status", ACTIVE_RUN_STATUSES)),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[uuid.UUID]
    attempt: Mapped[int] = mapped_column(Integer)
    production_id: Mapped[uuid.UUID]
    mode: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, default="en")
    variant_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(Text, default="accepted")
    current_step: Mapped[str | None] = mapped_column(Text)
    percent: Mapped[int] = mapped_column(Integer, default=0)
    settings_version: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict[str, Any]]
    input: Mapped[dict[str, Any]]
    deadline: Mapped[dt.datetime]
    cost_usd: Mapped[Decimal] = mapped_column(Cost, default=Decimal(0))
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    result: Mapped[dict[str, Any] | None]
    error: Mapped[dict[str, Any] | None]
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[dt.datetime | None]
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())
    started_at: Mapped[dt.datetime | None]
    finished_at: Mapped[dt.datetime | None]
    # Added in revision 0002: needed to send callbacks after a restart.
    callback_base_url: Mapped[str | None] = mapped_column(Text)
    credential_refs: Mapped[list[str] | None] = mapped_column(JSONB)
    traceparent: Mapped[str | None] = mapped_column(Text)


class Step(Base):
    __tablename__ = "steps"
    __table_args__ = (
        UniqueConstraint("run_id", "name", "try", name="uq_steps_run_name_try"),
        CheckConstraint(_in("status", STEP_STATUSES), name="ck_steps_status"),
        Index("ix_steps_input_hash", "input_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    try_: Mapped[int] = mapped_column("try", Integer, default=1)
    status: Mapped[str] = mapped_column(Text, default="pending")
    input_hash: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reused_from: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("steps.id", ondelete="SET NULL"))
    error: Mapped[dict[str, Any] | None]
    cost_usd: Mapped[Decimal] = mapped_column(Cost, default=Decimal(0))
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    num_turns: Mapped[int] = mapped_column(Integer, default=0)
    session_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime | None]
    finished_at: Mapped[dt.datetime | None]
    duration_s: Mapped[float | None] = mapped_column(Float)


class Check(Base):
    __tablename__ = "checks"
    __table_args__ = (
        CheckConstraint(_in("status", CHECK_STATUSES), name="ck_checks_status"),
        Index("ix_checks_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    step_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"))
    check_name: Mapped[str] = mapped_column("check", Text)
    status: Mapped[str] = mapped_column(Text)
    value: Mapped[Any | None] = mapped_column(JSONB)
    limit_value: Mapped[Any | None] = mapped_column("limit", JSONB)
    details: Mapped[dict[str, Any] | None]
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())


class SandboxRun(Base):
    __tablename__ = "sandbox_runs"
    __table_args__ = (
        CheckConstraint(_in("purpose", ("capture", "scratch")), name="ck_sandbox_runs_purpose"),
        Index("ix_sandbox_runs_step_id", "step_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(Text)
    image: Mapped[str] = mapped_column(Text)
    digest: Mapped[str | None] = mapped_column(Text)
    version_string: Mapped[str | None] = mapped_column(Text)
    container_id: Mapped[str | None] = mapped_column(Text)
    limits: Mapped[dict[str, Any] | None]
    exit: Mapped[str | None] = mapped_column(Text)
    log_ref: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())
    finished_at: Mapped[dt.datetime | None]


class AgentRun(Base):
    """One row per agent invocation, including resumes."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_step_id", "step_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"))
    container_id: Mapped[str | None] = mapped_column(Text)
    image_digest: Mapped[str | None] = mapped_column(Text)
    sdk_version: Mapped[str | None] = mapped_column(Text)
    cli_version: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[str | None] = mapped_column(Text)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Cost, default=Decimal(0))
    usage: Mapped[dict[str, Any] | None]
    transcript_ref: Mapped[str | None] = mapped_column(Text)
    egress_denied: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())
    finished_at: Mapped[dt.datetime | None]


class SourceCache(Base):
    __tablename__ = "source_cache"

    repo_url: Mapped[str] = mapped_column(Text, primary_key=True)
    commit: Mapped[str] = mapped_column(String(40), primary_key=True)
    volume: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())
    last_used_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())


class UsageLog(Base):
    """Counts for limits.max_jobs_per_day (UTC day) and limits.max_agent_runs_per_hour (sliding)."""

    __tablename__ = "usage_log"
    __table_args__ = (
        CheckConstraint(_in("kind", ("job", "agent_run")), name="ck_usage_log_kind"),
        Index("ix_usage_log_kind_at", "kind", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None]
    step: Mapped[str | None] = mapped_column(Text)
    at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())


class GoldenRun(Base):
    __tablename__ = "golden_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    requested_by: Mapped[str] = mapped_column(Text)
    overrides: Mapped[dict[str, Any] | None]
    status: Mapped[str] = mapped_column(Text, default="running")
    report: Mapped[dict[str, Any] | None]
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())
    finished_at: Mapped[dt.datetime | None]


class PromptVersion(Base):
    """An immutable runtime prompt version (D16 / C40). `skill` rows keep SKILL.md in `claude_md`."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("step", "version", name="uq_prompt_versions_step_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    step: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    claude_md: Mapped[str] = mapped_column(Text)
    task_md: Mapped[str] = mapped_column(Text, default="")
    placeholders: Mapped[dict[str, Any]] = mapped_column(JSONB, default=list)  # list of names
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sha256: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())


class PromptActive(Base):
    """The version a step uses when the job settings say `active`; `revision` is the `If-Match` value."""

    __tablename__ = "prompt_active"

    step: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())


class PromptAudit(Base):
    __tablename__ = "prompt_audit"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    at: Mapped[dt.datetime] = mapped_column(server_default=_now_default())
    actor: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)  # seed | create | activate
    step: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    previous_version: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
