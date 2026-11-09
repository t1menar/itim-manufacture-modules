"""Job input and stage output models (04 sections 2.2 and 2.5).

`/info` serves the JSON Schemas generated from these models as `input_schema` and
`output_schema`; the core validates the result callback against the output schema.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field


class ChannelSettings(BaseModel):
    """Channel settings read by the module (04 section 2.3). All keys are optional."""

    reading_wps: float | None = None
    caption_template: str | None = None
    hashtags: list[str] | None = None
    style_rules: list[str] | None = None
    palette: dict[str, str] | None = None


class Idea(BaseModel):
    id: int
    text: Annotated[str, Field(min_length=5, max_length=500)]
    language: Literal["en"]


class Channel(BaseModel):
    id: str
    language: Literal["en"]
    name: str | None = None
    settings: ChannelSettings | None = None


class Previous(BaseModel):
    script_ref: Annotated[str, Field(pattern=r"^s3://")]
    review_reason: Annotated[str, Field(min_length=1, max_length=4000)]
    round: Annotated[int, Field(ge=1)]


class JobInput(BaseModel):
    """The module view of `input` in the job request."""

    idea: Idea
    channels: Annotated[list[Channel], Field(min_length=1)]
    previous: Previous | None = None
    upstream: dict[str, Any] | None = None


class VideoFile(BaseModel):
    ref: str
    sha256: str
    duration_s: float
    size: int
    width: int
    height: int
    fps: int


class CheckResult(BaseModel):
    status: Literal["pass", "fail", "warn"]
    value: Any = None
    limit: Any = None


class Post(BaseModel):
    caption: str
    hashtags: list[str]


class Variant(BaseModel):
    language: Literal["en"]
    video: VideoFile
    contact_sheet: str
    cover: str
    post: Post
    checks: dict[str, CheckResult]


class StageOutput(BaseModel):
    """The `output` object of the result callback; exactly one variant in stage 1."""

    variants: Annotated[list[Variant], Field(min_length=1, max_length=1)]
    provenance: dict[str, Any]
    changes: str | None = None


def input_schema() -> dict[str, Any]:
    return JobInput.model_json_schema()


def output_schema() -> dict[str, Any]:
    return StageOutput.model_json_schema()


class Callback(BaseModel):
    base_url: str


class SettingsSnapshot(BaseModel):
    version: int
    values: dict[str, Any]


class JobRequest(BaseModel):
    """The canonical job request (AUTHORING section 4) as the module reads it."""

    job_id: uuid.UUID
    attempt: Annotated[int, Field(ge=1)]
    production_id: uuid.UUID
    stage: str
    mode: Literal["create", "revise"]
    variant: dict[str, Any] | None = None
    input: dict[str, Any]
    settings: SettingsSnapshot
    credentials: list[str] = []
    callback: Callback
    deadline: AwareDatetime
