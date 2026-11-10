"""The whole `scenario` step: research phase, then script phase, one pinned source tree for both."""

from __future__ import annotations

from typing import Any

from mscenario import agent as ag
from mscenario.script import ScriptService
from mscenario.service import Outcome, ResearchService


class ScenarioService:
    def __init__(self, research: ResearchService, script: ScriptService) -> None:
        self.research, self.script = research, script

    async def run(self, idea: dict[str, Any], step_key: str, revision: ag.Revision | None = None) -> Outcome:
        """`step_key` is the platform's key of this visit. The research is keyed by the idea revision instead, so a
        review round (a new step key) reuses it and only the script is rewritten."""
        pinned = await self.research.pin(idea)
        research = await self.research.run(idea, f"research:{idea['idea_ref']}", pinned)
        if research.status == "blocked":
            return Outcome("blocked", {**research.document, "phase": "research"}, research.usage, research.attempts)
        script = await self.script.run(idea, research.document, step_key, pinned[1], revision)
        usage = research.usage + script.usage
        if script.status == "blocked":
            return Outcome("blocked", {**script.document, "phase": "script"}, usage, script.attempts)
        doc = {"research": research.document, **script.document}
        return Outcome("done", doc, usage, research.attempts + script.attempts)
