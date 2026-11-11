"""Manufacture platform adapter: the `scenario` step as an SDK module.

Run with `mf-module run mscenario.adapter:app` (needs `manufacture-sdk`, env `MF_*` and `MSCENARIO_*`).
`step_key = ctx.step_key` and the revision round is `ctx.visit` (contract 0.3.0: the core counts the visits of the
stage and builds `revision` with CEL from `steps.scenario.visits[visit - 1].output` and the reviewer's comment; the
review-gate pattern). The research is keyed by the idea revision inside the service, so rounds only rewrite the
script. The cost of the attempt goes to the platform as `usage` (`ctx.add_usage`).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from manufacture import Context, Fatal, Module, NeedsAttention, Transient
from pydantic import BaseModel, Field

from mscenario import agent as ag
from mscenario.pipeline import ScenarioService
from mscenario.service import BudgetExceeded, ResearchInvalid, SourceNotAllowed
from mscenario.sources import SourceError


class RevisionIn(BaseModel):
    comment: str = Field(min_length=1)
    previous_script: dict[str, Any]
    previous_post: dict[str, Any] | None = None


class StepIn(BaseModel):
    idea: dict[str, Any]  # the idea document of module-idea (`idea_ref`, briefs, constraints, palette, ...)
    revision: RevisionIn | None = None


class StepOut(BaseModel):
    research: dict[str, Any]
    script: dict[str, Any]
    post: dict[str, Any]
    cost_usd: str
    attempts: int


Provider = Callable[[], Awaitable[ScenarioService]]


def report_usage(ctx: Context[Any], usage: ag.Usage) -> None:
    """Hand the attempt's cost and tokens (priced by the agents) to the platform."""
    models: dict[str | None, dict[str, int]] = dict(usage.tokens.items()) if usage.tokens else {None: {}}
    for i, (model, t) in enumerate(models.items()):
        ctx.add_usage(
            float(usage.cost_usd) if i == 0 else 0.0, model=model, input_tokens=t.get("input", 0),
            output_tokens=t.get("output", 0), cache_read=t.get("cache_read", 0), cache_write=t.get("cache_write", 0),
        )  # fmt: skip


def make_app(provider: Provider, name: str = "scenario", version: str = "0.1.0") -> Module[Any]:
    app = Module(name, version=version, concurrency=2)

    @app.step(input=StepIn, output=StepOut)
    async def handle(ctx: Context[Any], inp: StepIn) -> StepOut:
        svc = await provider()
        rev = inp.revision
        revision = ag.Revision(ctx.visit, rev.previous_script, rev.previous_post, rev.comment) if rev else None
        await ctx.progress(0.05, "research" if revision is None else "rewriting the script")
        try:
            out = await svc.run(inp.idea, ctx.step_key, revision)
        except BudgetExceeded as e:
            ctx.add_usage(float(e.spent))
            raise NeedsAttention(str(e), code="budget_exceeded") from e
        except ResearchInvalid as e:
            raise NeedsAttention(str(e), code="output_invalid_after_retries") from e
        except SourceNotAllowed as e:
            raise Fatal(str(e), code="source_not_allowed") from e
        except SourceError as e:
            raise Transient(str(e), code="source_unavailable", retry_after_s=30) from e
        if out.status == "blocked":
            reason = out.document.get("reason", "the idea cannot be shown honestly")
            raise NeedsAttention(f"{out.document.get('phase')}: {reason}", code="scenario_blocked")
        doc = out.document
        report_usage(ctx, out.usage)
        return StepOut(
            research=doc["research"], script=doc["script"], post=doc["post"],
            cost_usd=str(out.usage.cost_usd), attempts=out.attempts,
        )  # fmt: skip

    return app


_service: ScenarioService | None = None


async def _from_env() -> ScenarioService:
    """Production wiring: Postgres, git source checkout, Claude agents (`MSCENARIO_*`)."""
    global _service  # noqa: PLW0603
    if _service is None:
        from pathlib import Path  # noqa: PLC0415

        from mscenario.claude_agents import ClaudeResearchAgent, ClaudeScriptAgent  # noqa: PLC0415
        from mscenario.db import make_engine, make_sessionmaker  # noqa: PLC0415
        from mscenario.script import ScriptService  # noqa: PLC0415
        from mscenario.service import ResearchService, ResearchSettings  # noqa: PLC0415
        from mscenario.sources import GitSourceProvider  # noqa: PLC0415

        sm = make_sessionmaker(make_engine(os.environ["MSCENARIO_DATABASE_URL"]))
        settings = ResearchSettings(model=os.environ.get("MSCENARIO_MODEL"))
        work = os.environ.get("MSCENARIO_WORK_DIR")
        sources = GitSourceProvider(Path(work) if work else None)
        research = ResearchService(sm, sources, ClaudeResearchAgent(), settings)
        _service = ScenarioService(research, ScriptService(sm, ClaudeScriptAgent(), settings))
    return _service


app = make_app(_from_env)

__all__ = ["RevisionIn", "StepIn", "StepOut", "app", "make_app", "report_usage"]
