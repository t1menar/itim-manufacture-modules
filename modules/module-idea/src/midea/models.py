"""Tables of the idea module (Postgres in production, SQLite in unit tests: portable types only)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BigId = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[Any]: JSON}


class Environment(Base):
    """Where a video is recorded: sandbox image, version expectation, allowed source repositories."""

    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    sandbox_image: Mapped[str | None] = mapped_column(Text)
    version_expect: Mapped[str | None] = mapped_column(Text)
    allowed_repos: Mapped[list[Any]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Rubric(Base):
    """A recurring format: race, predict the output, break it, myth vs reality, what does it cost."""

    __tablename__ = "rubrics"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    template: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # scenario skeleton and limits


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")  # draft | active | archived
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    default_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"))
    rev: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    key_takeaway: Mapped[str | None] = mapped_column(Text)  # the one sentence the viewer must remember
    hook: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    rubric_code: Mapped[str | None] = mapped_column(ForeignKey("rubrics.code"))
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"))
    depth: Mapped[str] = mapped_column(String(8), default="broad")  # broad | deep
    difficulty: Mapped[int] = mapped_column(Integer, default=1)  # 1..5
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    demo_commands: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_result: Mapped[str | None] = mapped_column(Text)
    must_show: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_avoid: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_refs: Mapped[list[Any]] = mapped_column(JSON, default=list)  # {kind, url|repo, ref, note}
    references: Mapped[list[Any]] = mapped_column(JSON, default=list)
    constraints: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scenario_brief: Mapped[str | None] = mapped_column(Text)  # the owner's short script: what happens, in order
    video_brief: Mapped[str | None] = mapped_column(Text)  # how the video should feel: pace, tone, format
    design_notes: Mapped[str | None] = mapped_column(Text)  # visual wishes in words
    palette: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # colour token -> #RRGGBB overrides
    instructions: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # stage -> extra instructions for its agent
    target_duration_s: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    rev: Mapped[int] = mapped_column(Integer, default=1)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)  # current or last platform run
    dispatched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cost_spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal(0))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PlaylistIdea(Base):
    __tablename__ = "playlist_ideas"
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class IdeaRevision(Base):
    """Immutable snapshot of the idea document the pipeline was given (`idea:<id>:v<rev>`)."""

    __tablename__ = "idea_revisions"

    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdeaStatusLog(Base):
    __tablename__ = "idea_status_log"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), index=True)
    src: Mapped[str] = mapped_column(String(16))
    dst: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdeaRun(Base):
    """One platform run of an idea (an idea may be run again after a failure). Cost is idempotent per run."""

    __tablename__ = "idea_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), index=True)
    idea_rev: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="dispatched"
    )  # dispatched|running|succeeded|failed|cancelled
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdeaOutcome(Base):
    """Performance of a published video, to compare rubrics and depth by saves and follows per 1000 views."""

    __tablename__ = "idea_outcomes"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    idea_id: Mapped[int] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(Text)
    views: Mapped[int] = mapped_column(Integer, default=0)
    avg_watch_s: Mapped[float | None] = mapped_column(Numeric(8, 2))
    completion_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    saves: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    follows: Mapped[int] = mapped_column(Integer, default=0)
    measured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
