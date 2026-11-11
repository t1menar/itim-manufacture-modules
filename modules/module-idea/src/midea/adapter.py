"""Manufacture platform adapter: the idea scheduler as a source and the run status as a step.

`mf-module run midea.adapter:app` (needs `manufacture-sdk`; env `MF_*`, `MIDEA_DATABASE_URL`, optional
`MIDEA_PIPELINE`, `MIDEA_MAX_IN_FLIGHT`, `MIDEA_MIN_INTERVAL_S`).

- source (`source.trigger`, e.g. a platform schedule): picks queued ideas under the scheduler policy, binds each to a
  stable run id `src:<idea_ref>` and starts one run per idea (`dedup_key = idea_ref`, so a repeated trigger starts
  nothing twice). The run data is `{"idea": <idea document>}`: briefs, constraints, palette, instructions, environment.
- step `idea-status`: put it first (`running`) and last (`succeeded`) in the pipeline, and on the failure path
  (`failed`), until the platform has run lifecycle hooks (requirement R6). It reports status and the run cost.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import Any, Literal

from manufacture import Context, Fatal, Module, RunRequest, SourceContext
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from midea import schemas
from midea.db import transaction
from midea.service import IdeaService, SchedulerPolicy


class StatusIn(BaseModel):
    idea_ref: str
    status: Literal["running", "succeeded", "failed", "cancelled"]
    cost_usd: Decimal | None = Field(default=None, ge=0)
    error: str | None = None


class StatusOut(BaseModel):
    idea_ref: str
    idea_status: str | None  # None: a run this module did not start


Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def run_id_for(idea_ref: str) -> str:
    return f"src:{idea_ref}"


def make_app(
    tx: Transaction, policy: SchedulerPolicy, pipeline: str = "video", name: str = "idea", version: str = "0.1.0"
) -> Module[Any]:
    app = Module(name, version=version)

    @app.source(pipeline=pipeline)
    async def schedule(ctx: SourceContext[Any]) -> AsyncIterator[RunRequest]:
        async with tx() as s:
            svc = IdeaService(s)
            picked = await svc.pick_next(policy, limit=max(policy.max_in_flight, 1))
            docs = []
            for idea in picked:
                doc = await svc.build_document(idea)
                await svc.dispatch(idea.id, run_id_for(doc["idea_ref"]))
                docs.append(doc)
        for (
            doc
        ) in docs:  # published after the commit: a crash between leaves ideas `dispatched`, `release_stale` frees them
            yield RunRequest(data={"idea": doc}, dedup_key=doc["idea_ref"])

    @app.step(input=StatusIn, output=StatusOut)
    async def status(ctx: Context[Any], inp: StatusIn) -> StatusOut:
        if not inp.idea_ref.startswith("idea:"):
            raise Fatal(f"not an idea reference: {inp.idea_ref!r}", code="input_invalid")
        async with tx() as s:
            idea = await IdeaService(s).apply_run_event(
                schemas.RunEvent(
                    run_id=run_id_for(inp.idea_ref), status=inp.status, cost_usd=inp.cost_usd, error=inp.error
                )
            )
            return StatusOut(idea_ref=inp.idea_ref, idea_status=idea.status if idea else None)

    return app


def _from_env() -> Module[Any]:
    from midea.db import make_engine, make_sessionmaker  # noqa: PLC0415

    env = os.environ
    sm: async_sessionmaker[AsyncSession] = make_sessionmaker(make_engine(env["MIDEA_DATABASE_URL"]))
    policy = SchedulerPolicy(int(env.get("MIDEA_MAX_IN_FLIGHT", "3")), int(env.get("MIDEA_MIN_INTERVAL_S", "0")))
    return make_app(lambda: transaction(sm), policy, env.get("MIDEA_PIPELINE", "video"))


def __getattr__(name: str) -> Any:
    """`app` is built on first access so importing the module does not need the database settings."""
    if name == "app":
        return _from_env()
    raise AttributeError(name)


__all__ = ["StatusIn", "StatusOut", "make_app", "run_id_for"]
