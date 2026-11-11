"""Manufacture platform adapter: the `review` step as an SDK module (`mf-module run mtgr.adapter:app`).

One module, two gates: the pipeline picks the gate in the step `config` (`{gate: script|post}`). The step opens the
card and then *waits* (heartbeats keep the lease) until the owner decides; a restarted step finds the stored decision.
Output `outcome` is `approved` or `rejected` (+ `comment`, `round`); the pipeline routes `rejected` back to the stage
that owns the fix with `max_visits`. Escalated, expired or cancelled gates are `attention`.
`step_key = <run_id>:<step>:<round>`; the round travels in the input because the contract has no visit counter yet (R2).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from manufacture import Context, Fatal, Module, NeedsAttention
from pydantic import BaseModel, Field

from mtgr.service import Decision, OpenRequest, ReviewService

HEARTBEAT_S = 30.0


class Config(BaseModel):
    gate: Literal["script", "post"]


class StepIn(BaseModel):
    idea_ref: str
    round: int = Field(default=0, ge=0)  # 0 first visit; the pipeline counts revisions
    title: str = ""
    scenario: dict[str, Any] | None = None  # gate script: {script, post}
    variant: dict[str, Any] | None = None  # gate post: a variant of module-video-generation
    account: str | None = None
    cost_usd: float | None = None


class StepOut(BaseModel):
    outcome: Literal["approved", "rejected"]
    comment: str | None = None
    round: int


class Waiters:
    """`DecisionSink` that wakes the step waiting for its gate."""

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future[Decision]] = {}

    def future(self, step_key: str) -> asyncio.Future[Decision]:
        fut = self._futures.get(step_key)
        if fut is None or fut.done():
            fut = asyncio.get_running_loop().create_future()
            self._futures[step_key] = fut
        return fut

    async def decide(self, decision: Decision) -> None:
        fut = self._futures.get(decision.step_key)
        if fut is not None and not fut.done():
            fut.set_result(decision)

    def forget(self, step_key: str) -> None:
        self._futures.pop(step_key, None)


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


Provider = Callable[[], Awaitable[tuple[ReviewService, Waiters]]]


def make_app(provider: Provider, name: str = "telegram-review", version: str = "0.1.0") -> Module[Any]:
    app = Module(name, version=version, concurrency=8)

    @app.step(input=StepIn, output=StepOut)
    async def handle(ctx: Context[Any], inp: StepIn) -> StepOut:
        gate = ctx.config_as(Config).gate
        payload = script_payload(inp) if gate == "script" else post_payload(inp)
        if gate == "script" and not inp.scenario or gate == "post" and not inp.variant:
            raise Fatal(f"gate {gate} needs its content in the input", code="input_incomplete")
        svc, waiters = await provider()
        key = f"{ctx.run_id}:{ctx.step}:{inp.round}"
        fut = waiters.future(key)  # registered before the card is out: no lost wake-up
        try:
            await svc.open(OpenRequest(key, inp.idea_ref, gate, payload))
            decision = await svc.decision_for(key)
            while decision is None:
                try:
                    decision = await asyncio.wait_for(asyncio.shield(fut), HEARTBEAT_S)
                except TimeoutError:
                    await ctx.progress(None, "waiting for the review")
                    decision = await svc.decision_for(key)  # also covers a decision made by another replica
        finally:
            waiters.forget(key)
        if decision.outcome in {"approved", "rejected"}:
            return StepOut(outcome=decision.outcome, comment=decision.comment, round=decision.round)
        raise NeedsAttention(
            f"review gate {gate} {decision.outcome} (round {decision.round})", code=f"gate_{decision.outcome}"
        )

    return app


_state: tuple[ReviewService, Waiters] | None = None


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


async def _from_env() -> tuple[ReviewService, Waiters]:
    """Production wiring (`MTGR_*`): Postgres, Telegram Bot API, owner ids; starts the poller once."""
    global _state  # noqa: PLW0603
    if _state is None:
        from mtgr.bot import TelegramBot  # noqa: PLC0415
        from mtgr.db import make_engine, make_sessionmaker  # noqa: PLC0415
        from mtgr.service import ReviewSettings  # noqa: PLC0415

        env = os.environ
        waiters = Waiters()
        owners = frozenset(int(x) for x in env["MTGR_OWNERS"].split(",") if x.strip())
        cfg = ReviewSettings(owners, int(env.get("MTGR_MAX_ROUNDS", "3")), float(env.get("MTGR_DEADLINE_H", "48")))
        sm = make_sessionmaker(make_engine(env["MTGR_DATABASE_URL"]))
        svc = ReviewService(sm, TelegramBot(env["MTGR_BOT_TOKEN"], _file_loader), waiters, cfg)
        asyncio.get_running_loop().create_task(background(svc), name="mtgr-poller")
        _state = (svc, waiters)
    return _state


app = make_app(_from_env)

__all__ = ["Config", "StepIn", "StepOut", "Waiters", "app", "background", "make_app"]
