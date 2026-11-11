"""Sandbox catalog: which images exist, how their sessions start, what limits apply. Loaded from JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

ImageRef = Annotated[str, StringConstraints(pattern=r"^[^\s@]+@sha256:[0-9a-f]{64}$")]


class SandboxSession(BaseModel):
    kind: Literal["psql", "sh"] | None = None
    start: str | None = None
    title: str | None = None
    env: dict[str, Any] | None = None


class SandboxImage(BaseModel):
    image: ImageRef
    description: str | None = None
    env: dict[str, str] | None = None
    tmpfs: dict[str, str] | None = None
    cap_add: list[str] | None = None
    hostname: str | None = Field(default=None, description="`localhost` for servers that resolve their own name")
    exec_user: str | None = Field(default=None, description="user of the session processes (docker exec --user)")
    ready_cmd: str
    version_cmd: str
    version_expect: str
    sessions: dict[str, SandboxSession]


class SandboxLimits(BaseModel):
    cpus: float = 2
    memory_mb: int = 2048
    pids: int = 512
    command_timeout_s: int = 60
    total_timeout_s: int = 900
    ready_timeout_s: int = 60


class SandboxCatalog(BaseModel):
    images: dict[str, SandboxImage]
    limits: SandboxLimits = SandboxLimits()

    @classmethod
    def load(cls, path: str | Path) -> SandboxCatalog:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def describe(self, key: str) -> dict[str, Any]:
        """What the planner agent is told about an image: sessions and the version it expects."""
        img = self.images[key]
        return {
            "key": key, "version_expect": img.version_expect, "description": img.description,
            "sessions": {k: v.model_dump(exclude_none=True) for k, v in img.sessions.items()},
        }  # fmt: skip
