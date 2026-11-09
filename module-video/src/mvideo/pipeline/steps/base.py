"""Step interface. Real steps (analysis ... package) arrive in later phases."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mvideo.pipeline.context import RunContext
from mvideo.storage import Artifact


class Step(ABC):
    name: str
    version: str = "1"
    lo: int  # progress range of the step, 05 section 1 (analysis 0-5 ... package 90-100)
    hi: int
    uses_agent: bool = False  # agent steps are subject to limits.max_agent_runs_per_hour
    settings_keys: tuple[str, ...] = ()  # settings sections that change this step's output

    @abstractmethod
    async def run(self, ctx: RunContext) -> dict[str, Artifact]:
        """Do the work; return the files produced, already uploaded and confirmed."""
