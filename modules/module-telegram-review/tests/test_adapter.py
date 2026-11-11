from __future__ import annotations

import asyncio
from typing import Any

from manufacture.testing import call_step
from sqlalchemy import select

from mtgr.adapter import Waiters, make_app
from mtgr.bot import FakeBot
from mtgr.models import Session
from mtgr.service import ReviewService, ReviewSettings
from test_review import OWNER, POST, SCRIPT, tap, text

SCENARIO = {
    "script": {
        "meta": {"title": "T", "key_takeaway": "k"},
        "scenes": [{"id": "s1", "title": "Hook", "narration": "n"}],
    },
    "post": {"hook": "H", "summary": "S"},
}
VARIANT = {
    "video": POST["video"],
    "cover": {"ref": "s3://v/cover.jpg"},
    "post": POST["post"],
    "metadata": {"title": "T"},
}


def make(sm):  # type: ignore[no-untyped-def]
    bot, waiters = FakeBot(), Waiters()
    svc = ReviewService(sm, bot, waiters, ReviewSettings(frozenset({OWNER})))

    async def provider() -> tuple[ReviewService, Waiters]:
        return svc, waiters

    return make_app(provider), svc, bot


async def first_card(bot: FakeBot) -> None:
    for _ in range(200):
        if bot.cards:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no card was sent")


async def latest(sm):  # type: ignore[no-untyped-def]
    async with sm() as s:
        return (await s.scalars(select(Session).order_by(Session.id.desc()).limit(1))).one()


async def run_gate(sm, gate: str, data: dict[str, Any], decide):  # type: ignore[no-untyped-def]
    app, svc, bot = make(sm)
    task = asyncio.create_task(call_step(app, data, config={"gate": gate}, timeout_s=20))
    await first_card(bot)
    await decide(svc, (await latest(sm)).id)
    return await task, bot


async def test_script_gate_approved(sm) -> None:  # type: ignore[no-untyped-def]
    async def approve(svc, sid):  # type: ignore[no-untyped-def]
        await svc.handle(tap(1, sid, "ok"))

    res, bot = await run_gate(sm, "script", {"idea_ref": "idea:1:v1", "scenario": SCENARIO, "cost_usd": 0.4}, approve)
    assert res.type == "step.succeeded", res.payload
    assert res.payload["output"] == {"outcome": "approved", "comment": None, "round": 1}
    assert "Hook" in bot.cards[0][1].text and bot.cards[0][1].video is None


async def test_post_gate_rejected_with_comment(sm) -> None:  # type: ignore[no-untyped-def]
    async def reject(svc, sid):  # type: ignore[no-untyped-def]
        await svc.handle(tap(1, sid, "no"))
        await svc.handle(text(2, "shorter hook please"))

    res, bot = await run_gate(
        sm, "post", {"idea_ref": "idea:1:v1", "variant": VARIANT, "account": "main", "round": 1}, reject
    )
    assert res.payload["output"]["outcome"] == "rejected" and res.payload["output"]["comment"] == "shorter hook please"
    assert bot.cards[0][1].video == "s3://v/final.mp4" and "revision 0" not in bot.cards[0][1].text


async def test_missing_content_is_fatal(sm) -> None:  # type: ignore[no-untyped-def]
    app, _, _ = make(sm)
    res = await call_step(app, {"idea_ref": "i"}, config={"gate": "post"})
    assert res.payload["class"] == "fatal" and res.payload["code"] == "input_incomplete"


async def test_restarted_step_picks_up_an_existing_decision(sm) -> None:  # type: ignore[no-untyped-def]
    app, svc, bot = make(sm)
    task = asyncio.create_task(
        call_step(app, {"idea_ref": "idea:1:v1", "scenario": SCENARIO}, config={"gate": "script"}, timeout_s=20)
    )
    await first_card(bot)
    sid = (await latest(sm)).id
    await svc.handle(tap(1, sid, "ok"))
    await task
    again = await call_step(
        app, {"idea_ref": "idea:1:v1", "scenario": SCENARIO}, config={"gate": "script"}, timeout_s=20
    )
    assert again.payload["output"]["outcome"] == "approved" and len(bot.cards) == 1  # no second card


async def test_expired_gate_needs_attention(sm) -> None:  # type: ignore[no-untyped-def]
    app, svc, bot = make(sm)
    task = asyncio.create_task(
        call_step(app, {"idea_ref": "idea:1:v1", "scenario": SCENARIO}, config={"gate": "script"}, timeout_s=20)
    )
    await first_card(bot)
    assert await svc.cancel((await latest(sm)).step_key)
    res = await task
    assert res.payload["class"] == "attention" and res.payload["code"] == "gate_cancelled"
    _ = SCRIPT
