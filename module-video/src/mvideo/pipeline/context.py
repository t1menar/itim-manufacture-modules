"""What a step can see of the run it belongs to."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from mvideo.contract import JobInput
from mvideo.core_client import Credential
from mvideo.settings_model import VideoSettings
from mvideo.storage import Artifact, Storage, object_key


@dataclass(slots=True)
class RunContext:
    run_id: uuid.UUID
    job_id: uuid.UUID
    attempt: int
    production_id: uuid.UUID
    mode: str
    input: JobInput
    settings: VideoSettings
    storage: Storage
    credential: Credential | None = field(default=None, repr=False)
    outputs: dict[str, dict[str, Artifact]] = field(default_factory=dict)  # step name -> files so far

    def key(self, step: str, name: str) -> str:
        return object_key(str(self.production_id), self.attempt, step, name)
