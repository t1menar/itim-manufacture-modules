"""Manufacture platform adapter: the idea scheduler as a source, run lifecycle as notifications (contract 0.3.0).

`mf-module run midea.adapter:app` (needs `manufacture-sdk`; env `MF_*`, `MIDEA_DATABASE_URL`, optional
`MIDEA_PIPELINE`, `MIDEA_MAX_IN_FLIGHT`, `MIDEA_MIN_INTERVAL_S`). The Module resource must `subscribe` to
`run.started` and `run.finished` of the pipeline.

- source (`source.trigger`, the pipeline schedule): picks queued ideas under the scheduler policy and starts one run per
  idea (`dedup_key = idea_ref`, label `idea_ref`). The run data is `{"idea": <idea document>}`.
- `run.started` -> idea `in_production`; `run.finished` -> `done` / `failed` / `cancelled` with the run cost
  (`usage.cost_usd`, summed by the core). The idea is found by the `idea_ref` label; replays never move it back.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import Any

from manufacture import Module, RunRequest, SourceContext
from manufacture import _wire as wire
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from midea import schemas
from midea.db import transaction
from midea.service import IdeaService, SchedulerPolicy

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
            yield RunRequest(data={"idea": doc}, dedup_key=doc["idea_ref"], labels={"idea_ref": doc["idea_ref"]})

    async def apply(
        ev: wire.RunStarted | wire.RunFinished, status: str, cost: Decimal | None, error: str | None
    ) -> None:
        ref = ev.labels.get("idea_ref")
        if not ref or not ref.startswith("idea:"):
            return  # a run this module did not start
        async with tx() as s:
            await IdeaService(s).apply_run_event(
                schemas.RunEvent(run_id=run_id_for(ref), status=status, cost_usd=cost, error=error)
            )

    @app.on_run_started
    async def started(run_id: str, ev: wire.RunStarted) -> None:
        await apply(ev, "running", None, None)

    @app.on_run_finished
    async def finished(run_id: str, ev: wire.RunFinished) -> None:
        cost = Decimal(str(ev.usage.get("cost_usd", 0)))
        await apply(ev, ev.status, cost, ev.error.message if ev.error else None)

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


__all__ = ["make_app", "run_id_for"]
