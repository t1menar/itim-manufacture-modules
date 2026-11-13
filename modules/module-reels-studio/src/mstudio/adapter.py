"""Manufacture adapter: the `reels-studio` step (`config: {mode: script|video}`).

The handler only stores the job and parks the attempt (`ctx.wait(reason="external")`): a video takes hours and may
sleep through usage-limit resets. The worker (one job at a time) finishes it later with `app.complete` / `app.fail`.
`step_key` is the idempotency key: a retried attempt of a finished visit gets the stored output at once.
"""

from __future__ import annotations

from typing import Any, Literal

from manufacture import Context, Module, NeedsAttention
from pydantic import BaseModel, ConfigDict

from mstudio.store import Job, Store


class Config(BaseModel):
    mode: Literal["script", "video"]


class StepIn(BaseModel):
    idea: dict[str, Any]
    revision: dict[str, Any] | None = None  # {comment, round} when a reviewer rejected the previous visit
    scenario: dict[str, Any] | None = None  # video mode: the approved script
    episode: str | None = None


class StepOut(BaseModel):
    """script: {title, scenario: {script, post}, episode}; video: {title, variant: {video, cover, post, metadata}}."""

    model_config = ConfigDict(extra="allow")
    title: str = ""
    episode: str


class AppFinisher:
    def __init__(self, app: Module[Any]) -> None:
        self.app = app

    async def complete(self, handle: str, output: dict[str, Any], cost_usd: float | None) -> None:
        await self.app.complete(handle, output, cost_usd=cost_usd)

    async def fail(self, handle: str, message: str, code: str) -> None:
        await self.app.fail(handle, NeedsAttention(
            message, code=code,
            recommendation="Read ~/.local/state/reels-studio/logs, fix the cause, then retry the step.",
        ))  # fmt: skip


def make_app(store: Store, on_job: Any = None, name: str = "reels-studio", version: str = "0.1.0") -> Module[Any]:
    app = Module(name, version=version, concurrency=4)

    @app.step(input=StepIn, output=StepOut)
    async def handle(ctx: Context[Any], inp: StepIn) -> StepOut:
        mode = ctx.config_as(Config).mode
        known = store.get(ctx.step_key)
        if known is not None and known.state == "done" and known.output:
            return StepOut.model_validate(known.output)
        data = inp.model_dump()
        data["blob_prefix"] = ctx.blob_prefix
        store.put(Job(ctx.step_key, ctx.run_id, mode, ctx.visit, str(ctx.attempt_handle), data))
        if on_job is not None:
            on_job()
        await ctx.wait(reason="external", message=f"Claude Code is making the {mode} on the laptop")

    return app
