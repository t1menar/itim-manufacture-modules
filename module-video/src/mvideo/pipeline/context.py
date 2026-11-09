"""What a step can see of the run it belongs to."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

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
    # services of the real steps (None in tests of the plain flow)
    launcher: Any = None  # mvideo.agents.launcher.AgentLauncher
    source: Any = None  # mvideo.validate.source.SourceTree of the pinned checkout, for line checks
    docker: Any = None  # docker client (capture, source volume access)
    scratch: Any = None  # mvideo.api.mcp_sandbox.ScratchRegistry
    git_cache: Any = None  # mvideo.sources.git_cache.GitCache
    sandbox_mcp_url: str = ""
    fix_reports: dict[str, str] = field(default_factory=dict)  # step -> check report of a fix round
    usage: list[Any] = field(default_factory=list)  # Cost records of agent runs (accounted by the runner)
    # revise mode: files of the last succeeded run of the production, and what this run found out
    previous: dict[str, dict[str, Artifact]] = field(default_factory=dict)
    values_changed: list[str] = field(default_factory=list)
    sandbox_used: bool = (
        False  # set by the capture step when it ran a sandbox (revise tests assert it did not)
    )

    def files(self, step: str) -> dict[str, Artifact]:
        """Outputs of a step; in revise mode `script` is produced by `script-revise`."""
        if step == "script" and "script-revise" in self.outputs:
            return self.outputs["script-revise"]
        return self.outputs[step]

    def key(self, step: str, name: str) -> str:
        return object_key(str(self.production_id), self.attempt, step, name)
