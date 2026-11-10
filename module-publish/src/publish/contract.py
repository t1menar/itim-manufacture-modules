"""Job request models (contract 1)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class Callback(BaseModel):
    base_url: str


class SettingsSnapshot(BaseModel):
    version: int = 1
    values: dict[str, Any] = Field(default_factory=dict)


class VariantRef(BaseModel):
    id: uuid.UUID
    language: str = "en"


class JobRequest(BaseModel):
    job_id: uuid.UUID
    attempt: int = Field(ge=1)
    try_: int | None = Field(default=None, alias="try")
    fence: int = Field(default=1, ge=1)
    production_id: uuid.UUID
    stage: str
    mode: Literal["create", "revise", "republish"] = "create"
    variant: VariantRef | None = None
    input: dict[str, Any]
    settings: SettingsSnapshot = Field(default_factory=SettingsSnapshot)
    credentials: list[str] = Field(default_factory=list)
    callback: Callback
    deadline: str  # ISO8601; parsed in intake

    model_config = {"populate_by_name": True}
