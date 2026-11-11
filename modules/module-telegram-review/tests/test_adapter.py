from __future__ import annotations

from typing import Any

from manufacture import AttemptHandle
from manufacture.runtime import Runtime
from manufacture.settings import RuntimeSettings
from manufacture.testing import ATTEMPT_ID, RUN_ID, FakeTransport, step_request
from sqlalchemy import select

from mtgr.adapter import AppSink, make_app
from mtgr.bot import FakeBot
from mtgr.models import Session
from mtgr.service import ReviewService, ReviewSettings
from test_review import OWNER, POST, tap, text

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


class Harness:
    """A module replica on the in-memory transport plus a review service whose decisions complete the attempt."""

    def __init__(self, sm) -> None:  # type: ignore[no-untyped-def]
        self.sm, self.bot, self.transport = sm, FakeBot(), FakeTransport()
        self.svc: ReviewService | None = None
        self.app = make_app(self._provider)
        self.runtime = Runtime(
            self.app,
            settings=RuntimeSettings(health_addr="", replica_id="r1", module_heartbeat_s=3600, publish_timeout_s=2),
            transport=self.transport,
        )

    async def _provider(self) -> ReviewService:
        if self.svc is None:
            self.svc = ReviewService(self.sm, self.bot, AppSink(lambda: self.app), ReviewSettings(frozenset({OWNER})))
        return self.svc

    async def __aenter__(self) -> Harness:
        await self.runtime.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.runtime.stop()

    async def start(self, gate: str, data: dict[str, Any], **kw: Any) -> None:
        await self.transport.deliver(step_request(data, config={"gate": gate}, **kw))
        await self.transport.wait_for("step.waiting")

    async def latest(self) -> Session:
        async with self.sm() as s:
            return (await s.scalars(select(Session).order_by(Session.id.desc()).limit(1))).one()


async def test_script_gate_waits_and_approval_completes_the_attempt(sm) -> None:  # type: ignore[no-untyped-def]
    async with Harness(sm) as h:
        await h.start("script", {"idea_ref": "idea:1:v1", "scenario": SCENARIO, "cost_usd": 0.4})
        (waiting,) = h.transport.of_type("step.waiting")
        assert waiting.payload["reason"] == "human"
        row = await h.latest()
        assert row.attempt_handle == str(AttemptHandle(RUN_ID, ATTEMPT_ID, 1))
        assert "Hook" in h.bot.cards[0][1].text and h.bot.cards[0][1].video is None
        assert h.svc is not None
        await h.svc.handle(tap(1, row.id, "ok"))
        (done,) = await h.transport.wait_for("step.succeeded")
        assert done.payload["output"] == {"outcome": "approved", "comment": None, "round": 1}


async def test_post_gate_rejection_with_comment_completes_with_rejected(sm) -> None:  # type: ignore[no-untyped-def]
    async with Harness(sm) as h:
        await h.start("post", {"idea_ref": "idea:1:v1", "variant": VARIANT, "account": "main"})
        row = await h.latest()
        assert h.bot.cards[0][1].video == "s3://v/final.mp4"
        assert h.svc is not None
        await h.svc.handle(tap(1, row.id, "no"))
        assert not h.transport.of_type("step.succeeded")  # still waiting for the comment
        await h.svc.handle(text(2, "shorter hook please"))
        (done,) = await h.transport.wait_for("step.succeeded")
        assert done.payload["output"]["outcome"] == "rejected"
        assert done.payload["output"]["comment"] == "shorter hook please"


async def test_missing_content_is_fatal(sm) -> None:  # type: ignore[no-untyped-def]
    async with Harness(sm) as h:
        await h.transport.deliver(step_request({"idea_ref": "i"}, config={"gate": "post"}))
        (failed,) = await h.transport.wait_for("step.failed")
        assert failed.payload["class"] == "fatal" and failed.payload["code"] == "input_incomplete"


async def test_retried_attempt_takes_over_the_session_and_gets_the_decision(sm) -> None:  # type: ignore[no-untyped-def]
    other = "33333333-3333-4333-8333-333333333333"
    async with Harness(sm) as h:
        await h.start("script", {"idea_ref": "idea:1:v1", "scenario": SCENARIO})
        # the first attempt was lost; the core runs attempt 2 of the same visit (same step_key)
        await h.transport.deliver(
            step_request(
                {"idea_ref": "idea:1:v1", "scenario": SCENARIO}, config={"gate": "script"}, attempt_id=other, attempt=2
            )
        )
        await h.transport.wait_for("step.waiting", count=2)
        row = await h.latest()
        assert len(h.bot.cards) == 1 and row.attempt_handle == str(AttemptHandle(RUN_ID, other, 2))
        assert h.svc is not None
        await h.svc.handle(tap(1, row.id, "ok"))
        (done,) = await h.transport.wait_for("step.succeeded")
        assert done.envelope.attempt is not None and done.envelope.attempt.id == other


async def test_finished_gate_is_returned_at_once_to_a_new_attempt(sm) -> None:  # type: ignore[no-untyped-def]
    other = "33333333-3333-4333-8333-333333333333"
    async with Harness(sm) as h:
        await h.start("script", {"idea_ref": "idea:1:v1", "scenario": SCENARIO})
        row = await h.latest()
        assert h.svc is not None
        await h.svc.handle(tap(1, row.id, "ok"))
        await h.transport.wait_for("step.succeeded")
        await h.transport.deliver(
            step_request(
                {"idea_ref": "idea:1:v1", "scenario": SCENARIO}, config={"gate": "script"}, attempt_id=other, attempt=2
            )
        )
        await h.transport.wait_for("step.succeeded", count=2)
        assert len(h.bot.cards) == 1  # no second card


async def test_cancelled_gate_fails_the_attempt_as_attention(sm) -> None:  # type: ignore[no-untyped-def]
    async with Harness(sm) as h:
        await h.start("script", {"idea_ref": "idea:1:v1", "scenario": SCENARIO})
        row = await h.latest()
        assert h.svc is not None and await h.svc.cancel(row.step_key)
        (failed,) = await h.transport.wait_for("step.failed")
        assert failed.payload["class"] == "attention" and failed.payload["code"] == "gate_cancelled"
        assert "recommendation" in failed.payload
