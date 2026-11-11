"""Manufacture platform adapter: the `review` step as an SDK module (`mf-module run mtgr.adapter:app`).

One module, two gates: the pipeline picks the gate in the step `config` (`{gate: script|post}`). The step opens the
card and parks the attempt with `ctx.wait` (contract 0.3.0: no lease, no execution timeout, the core's `wait.timeout`
and `on_timeout: attention` apply). When the owner decides, the poller finishes the attempt from whichever replica
runs it with `app.complete` (`AppSink`), at-least-once. `step_key = ctx.step_key` (one card per visit of the stage; a
retried attempt finds its session and takes over the new attempt handle). Output `outcome` is `approved` or
`rejected` (+ `comment`, `round`); the pipeline routes `rejected` back with `max_visits`. Escalated, expired or
cancelled gates fail the attempt as `attention`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from manufacture import Context, Fatal, Module, NeedsAttention
from pydantic import BaseModel

from mtgr.service import Decision, OpenRequest, ReviewService


class Config(BaseModel):
    gate: Literal["script", "post"]


class StepIn(BaseModel):
    idea_ref: str
    title: str = ""
    scenario: dict[str, Any] | None = None  # gate script: {script, post}
    variant: dict[str, Any] | None = None  # gate post: a variant of module-video-generation
    account: str | None = None
    cost_usd: float | None = None


class StepOut(BaseModel):
    outcome: Literal["approved", "rejected"]
    comment: str | None = None
    round: int


class AppSink:
    """`DecisionSink`: finishes the waiting platform attempt through the module (`Module.complete` / `fail`)."""

    def __init__(self, app: Callable[[], Module[Any]]) -> None:
        self._app = app

    async def decide(self, decision: Decision) -> None:
        if not decision.handle:
            raise RuntimeError("decision without an attempt handle")  # redelivered once the step re-opens it
        app = self._app()
        if decision.outcome in {"approved", "rejected"}:
            out = StepOut(outcome=decision.outcome, comment=decision.comment, round=decision.round)
            await app.complete(decision.handle, out)
        else:
            await app.fail(decision.handle, _attention(decision))


def _attention(decision: Decision) -> NeedsAttention:
    return NeedsAttention(
        f"review gate {decision.gate} {decision.outcome} (round {decision.round})",
        code=f"gate_{decision.outcome}",
        recommendation="Retry the step to reopen the card, skip it with a manual output, or cancel the run.",
    )


def script_payload(inp: StepIn) -> dict[str, Any]:
    sc = inp.scenario or {}
    script, post = sc.get("script") or {}, sc.get("post") or {}
    meta = script.get("meta") or {}
    return {
        "title": inp.title or meta.get("title", ""), "hook": post.get("hook") or meta.get("hook"),
        "takeaway": meta.get("key_takeaway"),
        "scenes": [
            {"id": x.get("id"), "title": x.get("title"), "narration": x.get("narration") or x.get("voice", "")}
            for x in script.get("scenes", [])
        ],
        "post": post, "cost_usd": inp.cost_usd,
    }  # fmt: skip


def post_payload(inp: StepIn) -> dict[str, Any]:
    v = inp.variant or {}
    return {
        "title": inp.title or (v.get("metadata") or {}).get("title", ""), "video": v.get("video"),
        "cover": (v.get("cover") or {}).get("ref"), "post": v.get("post"), "account": inp.account,
        "cost_usd": inp.cost_usd,
    }  # fmt: skip


Provider = Callable[[], Awaitable[ReviewService]]


def make_app(provider: Provider, name: str = "telegram-review", version: str = "0.1.0") -> Module[Any]:
    app = Module(name, version=version, concurrency=8)

    @app.step(input=StepIn, output=StepOut)
    async def handle(ctx: Context[Any], inp: StepIn) -> StepOut:
        gate = ctx.config_as(Config).gate
        payload = script_payload(inp) if gate == "script" else post_payload(inp)
        if gate == "script" and not inp.scenario or gate == "post" and not inp.variant:
            raise Fatal(f"gate {gate} needs its content in the input", code="input_incomplete")
        svc = await provider()
        key = ctx.step_key
        await svc.open(OpenRequest(key, inp.idea_ref, gate, payload, handle=str(ctx.attempt_handle)))
        decision = await svc.decision_for(key)  # a retried attempt may find the decision already made
        if decision is not None:
            if decision.outcome in {"approved", "rejected"}:
                return StepOut(outcome=decision.outcome, comment=decision.comment, round=decision.round)
            raise _attention(decision)
        await ctx.wait(reason="human", message=f"review gate {gate} in Telegram")

    return app


_state: ReviewService | None = None


def _s3_client() -> Any | None:
    if not os.environ.get("S3_ENDPOINT"):
        return None
    from mf_storage.client import StorageClient, StorageConfig  # noqa: PLC0415

    return StorageClient(StorageConfig.from_mapping(dict(os.environ)))


async def _file_loader(uri: str) -> bytes:
    if uri.startswith("s3://"):
        client = _s3_client()
        if client is None:
            raise Fatal("S3_ENDPOINT is not set", code="media_ref_unsupported")
        return bytes(await asyncio.to_thread(client.get_bytes, uri))
    if not uri.startswith("file://"):
        raise Fatal(f"unsupported media ref {uri!r}", code="media_ref_unsupported")
    return await asyncio.to_thread(lambda: open(uri.removeprefix("file://"), "rb").read())  # noqa: SIM115


async def background(svc: ReviewService, every_s: float = 5.0) -> None:
    """Long-polls Telegram and keeps the gates healthy: unsent cards, undelivered decisions, deadlines."""
    offset = 0
    tick = 0
    while True:
        try:
            offset = await svc.poll_once(offset)
            tick += 1
            if tick % max(int(60 / every_s), 1) == 0:
                await svc.resend_unsent()
                await svc.redeliver()
                await svc.expire_due()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a Telegram hiccup must not kill the poller
            await asyncio.sleep(every_s)


async def _from_env() -> ReviewService:
    """Production wiring (`MTGR_*`): Postgres, Telegram Bot API, owner ids; starts the poller once."""
    global _state  # noqa: PLW0603
    if _state is None:
        from mtgr.bot import TelegramBot  # noqa: PLC0415
        from mtgr.db import make_engine, make_sessionmaker  # noqa: PLC0415
        from mtgr.service import ReviewSettings  # noqa: PLC0415

        env = os.environ
        owners = frozenset(int(x) for x in env["MTGR_OWNERS"].split(",") if x.strip())
        cfg = ReviewSettings(owners, int(env.get("MTGR_MAX_ROUNDS", "3")), float(env.get("MTGR_DEADLINE_H", "48")))
        sm = make_sessionmaker(make_engine(env["MTGR_DATABASE_URL"]))
        svc = ReviewService(sm, TelegramBot(env["MTGR_BOT_TOKEN"], _file_loader), AppSink(lambda: app), cfg)
        asyncio.get_running_loop().create_task(background(svc), name="mtgr-poller")
        _state = svc
    return _state


app = make_app(_from_env)

__all__ = ["AppSink", "Config", "StepIn", "StepOut", "app", "background", "make_app"]
