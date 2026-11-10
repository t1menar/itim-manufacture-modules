"""Pydantic models of the HTTP API and of the idea document handed to the pipeline."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Depth = Literal["broad", "deep"]


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
INSTRUCTION_STAGES = ("research", "scenario", "video")


def _check_palette(value: dict[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return value
    for token, color in value.items():
        if not TOKEN.match(token):
            raise ValueError(f"palette token {token!r} must be snake_case")
        if not HEX_COLOR.match(color):
            raise ValueError(f"palette colour for {token!r} must look like #RRGGBB")
    return value


def _check_instructions(value: dict[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return value
    for stage, text in value.items():
        if stage not in INSTRUCTION_STAGES:
            raise ValueError(f"instructions stage {stage!r} must be one of {', '.join(INSTRUCTION_STAGES)}")
        if len(text) > 4000:
            raise ValueError(f"instructions for {stage!r} are longer than 4000 characters")
    return value


def _check_constraints(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Known keys are checked, unknown ones pass through: stages read what they understand."""
    if value is None:
        return value
    Constraints.model_validate(value)
    return value


class Constraints(BaseModel):
    """What stages understand today. Everything is optional; there are no defaults here."""

    model_config = ConfigDict(extra="allow")

    duration_s: dict[str, float] | None = None  # {min, max}
    max_scenes: int | None = Field(default=None, ge=1, le=30)
    hook_max_lines: int | None = Field(default=None, ge=1, le=6)
    caption_max_lines: int | None = Field(default=None, ge=1, le=6)
    note_max_lines: int | None = Field(default=None, ge=1, le=6)
    reading_wps: float | None = Field(default=None, gt=0, le=10)
    allowed_domains: list[str] | None = None
    voice: bool | None = None
    max_cost_usd: float | None = Field(default=None, gt=0)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EnvironmentIn(_In):
    code: Code
    title: str = Field(min_length=1)
    description: str | None = None
    sandbox_image: str | None = None
    version_expect: str | None = None
    allowed_repos: list[Any] = []
    active: bool = True


class EnvironmentOut(_Out):
    id: int
    code: str
    title: str
    description: str | None
    sandbox_image: str | None
    version_expect: str | None
    allowed_repos: list[Any]
    active: bool


class RubricIn(_In):
    code: Code
    title: str = Field(min_length=1)
    description: str | None = None
    template: dict[str, Any] = {}


class RubricOut(_Out):
    code: str
    title: str
    description: str | None
    template: dict[str, Any]


class PlaylistIn(_In):
    code: Code
    title: str = Field(min_length=1)
    description: str | None = None
    status: Literal["draft", "active", "archived"] = "active"
    sort_order: int = 0
    default_tags: list[str] = []
    environment_code: str | None = None


class PlaylistPatch(_In):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: Literal["draft", "active", "archived"] | None = None
    sort_order: int | None = None
    default_tags: list[str] | None = None


class PlaylistOut(_Out):
    id: int
    code: str
    title: str
    description: str | None
    status: str
    sort_order: int
    default_tags: list[str]
    environment_id: int | None
    rev: int


class PlaylistDetail(PlaylistOut):
    idea_ids: list[int] = []


class IdeaIn(_In):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    key_takeaway: str | None = Field(default=None, max_length=300)
    hook: str | None = Field(default=None, max_length=300)
    audience: str | None = None
    language: str = "en"
    rubric_code: str | None = None
    environment_code: str | None = None
    depth: Depth = "broad"
    difficulty: int = Field(default=1, ge=1, le=5)
    tags: list[str] = Field(default=[], max_length=20)
    demo_commands: list[str] = Field(default=[], max_length=6)
    expected_result: str | None = None
    must_show: list[str] = []
    must_avoid: list[str] = []
    source_refs: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    constraints: dict[str, Any] | None = None
    target_duration_s: int | None = Field(default=None, ge=10, le=180)
    priority: int = Field(default=0, ge=-100, le=100)
    notes: str | None = None
    author: str | None = None
    playlist_codes: list[str] = []
    scenario_brief: str | None = Field(default=None, max_length=6000)
    video_brief: str | None = Field(default=None, max_length=3000)
    design_notes: str | None = Field(default=None, max_length=3000)
    palette: dict[str, str] | None = None
    instructions: dict[str, str] | None = None

    @field_validator("constraints")
    @classmethod
    def _constraints(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _check_constraints(v)

    @field_validator("palette")
    @classmethod
    def _palette(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _check_palette(v)

    @field_validator("instructions")
    @classmethod
    def _instructions(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _check_instructions(v)


class IdeaPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    key_takeaway: str | None = Field(default=None, max_length=300)
    hook: str | None = Field(default=None, max_length=300)
    audience: str | None = None
    language: str | None = None
    rubric_code: str | None = None
    environment_code: str | None = None
    depth: Depth | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = Field(default=None, max_length=20)
    demo_commands: list[str] | None = Field(default=None, max_length=6)
    expected_result: str | None = None
    must_show: list[str] | None = None
    must_avoid: list[str] | None = None
    source_refs: list[dict[str, Any]] | None = None
    references: list[dict[str, Any]] | None = None
    constraints: dict[str, Any] | None = None
    target_duration_s: int | None = Field(default=None, ge=10, le=180)
    priority: int | None = Field(default=None, ge=-100, le=100)
    notes: str | None = None
    scenario_brief: str | None = Field(default=None, max_length=6000)
    video_brief: str | None = Field(default=None, max_length=3000)
    design_notes: str | None = Field(default=None, max_length=3000)
    palette: dict[str, str] | None = None
    instructions: dict[str, str] | None = None

    @field_validator("constraints")
    @classmethod
    def _constraints(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _check_constraints(v)

    @field_validator("palette")
    @classmethod
    def _palette(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _check_palette(v)

    @field_validator("instructions")
    @classmethod
    def _instructions(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _check_instructions(v)


class IdeaOut(_Out):
    id: int
    title: str
    description: str
    key_takeaway: str | None
    hook: str | None
    audience: str | None
    language: str
    rubric_code: str | None
    environment_id: int | None
    depth: str
    difficulty: int
    tags: list[str]
    demo_commands: list[str]
    expected_result: str | None
    must_show: list[str]
    must_avoid: list[str]
    source_refs: list[Any]
    references: list[Any]
    constraints: dict[str, Any] | None
    target_duration_s: int | None
    priority: int
    notes: str | None
    scenario_brief: str | None
    video_brief: str | None
    design_notes: str | None
    palette: dict[str, str] | None
    instructions: dict[str, str] | None
    author: str | None
    status: str
    rev: int
    run_id: str | None
    cost_spent_usd: Decimal
    last_error: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class StatusChange(_In):
    status: Literal["draft", "queued", "archived"]
    note: str | None = None


class PlaylistAdd(_In):
    idea_id: int
    position: int | None = None


class PlaylistOrder(_In):
    idea_ids: list[int]


class OutcomeIn(_In):
    platform: str = "instagram"
    external_id: str | None = None
    views: int = Field(ge=0)
    avg_watch_s: float | None = Field(default=None, ge=0)
    completion_rate: float | None = Field(default=None, ge=0, le=1)
    saves: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    follows: int = Field(default=0, ge=0)
    measured_at: dt.datetime | None = None


class OutcomeOut(_Out):
    id: int
    idea_id: int
    platform: str
    external_id: str | None
    views: int
    saves: int
    shares: int
    follows: int
    measured_at: dt.datetime


class GroupStat(BaseModel):
    key: str
    ideas: int
    views: int
    saves_per_1000: float
    shares_per_1000: float
    follows_per_1000: float
    cost_usd: Decimal


class RunEvent(_In):
    """What the pipeline reports about a run (a platform `run.started` / `run.finished` event)."""

    run_id: str
    status: Literal["running", "succeeded", "failed", "cancelled"]
    cost_usd: Decimal | None = Field(default=None, ge=0)
    error: str | None = None
    occurred_at: dt.datetime | None = None
