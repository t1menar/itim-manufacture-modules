from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from mtgr.bot import FakeBot, TelegramBot, TelegramError, Update
from mtgr.cards import build_card, parse_callback
from mtgr.service import Decision, OpenRequest, ReviewService, ReviewSettings

OWNER = 42
SCRIPT = {
    "title": "How CREATE DATABASE works", "hook": "It copies.", "takeaway": "a template copy",
    "scenes": [{"id": "s1", "title": "Hook", "narration": "<b>Nothing</b> is created & copied"}],
    "post": {"summary": "What happens"}, "cost_usd": 0.42,
}  # fmt: skip
POST = {
    "title": "How CREATE DATABASE works", "video": {"ref": "s3://v/final.mp4", "duration_s": 38.2, "size": 9_100_000},
    "cover": "s3://v/cover.jpg", "post": {"caption": "Hook\n\nSource: x", "hashtags": ["#sql", "#db"]},
    "account": "main", "cost_usd": 1.1,
}  # fmt: skip


class Sink:
    def __init__(self) -> None:
        self.got: list[Decision] = []
        self.fail = False

    async def decide(self, decision: Decision) -> None:
        if self.fail:
            raise RuntimeError("platform down")
        self.got.append(decision)


def make(sm, **kw):  # type: ignore[no-untyped-def]
    bot, sink = FakeBot(), Sink()
    cfg = ReviewSettings(owners=frozenset({OWNER}), **kw)
    return ReviewService(sm, bot, sink, cfg), bot, sink


def tap(uid: int, sid: int, action: str, user: int = OWNER, mid: int = 101) -> Update:
    return Update(uid, OWNER, user, "callback", f"r:{sid}:{action}", f"cb{uid}", mid)


def text(uid: int, msg: str, chat: int = OWNER) -> Update:
    return Update(uid, chat, chat, "text", msg, None, 7)


def test_cards_for_both_gates_escape_html_and_have_two_buttons() -> None:
    c1 = build_card("script", SCRIPT, 1, 5)
    assert "&lt;b&gt;Nothing" in c1.text and c1.video is None and len(c1.buttons) == 2 and "$0.42" in c1.text
    c2 = build_card("post", POST, 3, 6)
    assert c2.video == "s3://v/final.mp4" and "revision 2" in c2.text and "38 s" in c2.text and "#sql #db" in c2.text
    assert parse_callback(c2.buttons[0][1]) == (6, "ok") and parse_callback("x:1:ok") is None
    with pytest.raises(ValueError):
        build_card("nope", {}, 1, 1)


async def test_approve_flow_delivers_once(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    s = await svc.open(OpenRequest("run1:review1", "idea:1:v1", "script", SCRIPT))
    again = await svc.open(OpenRequest("run1:review1", "idea:1:v1", "script", SCRIPT))  # retried step
    assert len(bot.cards) == 1 and again.id == s.id and s.message_id == 101
    await svc.handle(tap(1, s.id, "ok"))
    await svc.handle(tap(1, s.id, "ok"))  # redelivered update
    await svc.handle(tap(2, s.id, "no"))  # late tap on a decided card
    assert [d.outcome for d in sink.got] == ["approved"] and bot.cleared == [(OWNER, 101)]
    assert bot.answers[-1][1] == "Already handled"


async def test_reject_waits_for_the_comment_then_requests_a_revision(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    s = await svc.open(OpenRequest("run1:review2", "idea:1:v1", "post", POST))
    await svc.handle(tap(1, s.id, "no"))
    assert not sink.got and (await svc.get("run1:review2")).status == "awaiting_comment"  # type: ignore[union-attr]
    await svc.handle(text(2, "  make the hook shorter  "))
    assert sink.got == [Decision("run1:review2", "idea:1:v1", "post", "rejected", 1, "make the hook shorter")]
    assert any("fixing now" in t for _, t, _ in bot.texts)


async def test_text_without_a_waiting_card_is_answered(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    await svc.handle(text(1, "hello"))
    assert not sink.got and bot.texts[-1][1] == "No card is waiting for a comment."


async def test_revised_card_replies_to_the_previous_one_and_counts_rounds(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    s1 = await svc.open(OpenRequest("r:v1", "idea:1:v1", "post", POST))
    await svc.handle(tap(1, s1.id, "no"))
    await svc.handle(text(2, "fix it"))
    s2 = await svc.open(OpenRequest("r:v2", "idea:1:v1", "post", POST))
    assert s2.round == 2 and bot.cards[1][2] == s1.message_id and "revision 1" in bot.cards[1][1].text


async def test_round_limit_escalates_instead_of_looping(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm, max_rounds=1)
    s1 = await svc.open(OpenRequest("r:v1", "idea:1:v1", "script", SCRIPT))
    await svc.handle(tap(1, s1.id, "no"))
    await svc.handle(text(2, "again"))
    s2 = await svc.open(OpenRequest("r:v2", "idea:1:v1", "script", SCRIPT))
    assert s2.status == "escalated" and len(bot.cards) == 1 and sink.got[-1].outcome == "escalated"


async def test_gates_count_rounds_independently(sm) -> None:  # type: ignore[no-untyped-def]
    svc, _, _ = make(sm, max_rounds=1)
    a = await svc.open(OpenRequest("r:a", "idea:1:v1", "script", SCRIPT))
    await svc.handle(tap(1, a.id, "no"))
    await svc.handle(text(2, "x"))
    b = await svc.open(OpenRequest("r:b", "idea:1:v1", "post", POST))
    assert b.status == "pending" and b.round == 1


async def test_strangers_cannot_decide(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    s = await svc.open(OpenRequest("r:1", "idea:1:v1", "script", SCRIPT))
    await svc.handle(Update(1, 999, 999, "callback", f"r:{s.id}:ok", "cbx", 101))
    assert not sink.got and bot.answers[-1][1] == "Not allowed"


async def test_undelivered_decisions_are_resent(sm) -> None:  # type: ignore[no-untyped-def]
    svc, _, sink = make(sm)
    s = await svc.open(OpenRequest("r:1", "idea:1:v1", "script", SCRIPT))
    sink.fail = True
    await svc.handle(tap(1, s.id, "ok"))
    assert not sink.got and not (await svc.get("r:1")).delivered  # type: ignore[union-attr]
    sink.fail = False
    assert await svc.redeliver() == 1 and sink.got[0].outcome == "approved"
    assert await svc.redeliver() == 0


async def test_unsent_card_is_retried(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, _ = make(sm)
    bot.fail_sends = 1
    s = await svc.open(OpenRequest("r:1", "idea:1:v1", "script", SCRIPT))
    assert s.message_id is None and await svc.resend_unsent() == 1
    assert (await svc.get("r:1")).message_id is not None and len(bot.cards) == 1  # type: ignore[union-attr]


async def test_deadline_expires_open_gates(sm) -> None:  # type: ignore[no-untyped-def]
    svc, _, sink = make(sm, deadline_h=1)
    await svc.open(OpenRequest("r:1", "idea:1:v1", "script", SCRIPT))
    assert await svc.expire_due(datetime.now(UTC) + timedelta(minutes=30)) == 0
    assert await svc.expire_due(datetime.now(UTC) + timedelta(hours=2)) == 1 and sink.got[0].outcome == "expired"


async def test_cancel_and_notify(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    a = await svc.open(OpenRequest("r:1", "idea:1:v1", "post", POST))
    assert await svc.cancel("r:1") and not await svc.cancel("r:1") and sink.got[-1].outcome == "cancelled"
    b = await svc.open(OpenRequest("r:2", "idea:2:v1", "post", POST))
    await svc.handle(tap(1, b.id, "ok"))
    assert await svc.notify_published("idea:2:v1", "Published: https://i/x")
    assert bot.texts[-1] == (OWNER, "Published: https://i/x", b.message_id) and not await svc.notify_published(
        "idea:9", "x"
    )
    _ = a


async def test_poll_once_advances_the_offset(sm) -> None:  # type: ignore[no-untyped-def]
    svc, bot, sink = make(sm)
    s = await svc.open(OpenRequest("r:1", "idea:1:v1", "script", SCRIPT))
    bot.queue = [tap(10, s.id, "ok"), Update(11, 0, 0, "ignored")]
    assert await svc.poll_once(0) == 12 and sink.got[0].outcome == "approved"


async def test_real_bot_sends_video_with_buttons_and_hides_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})

    async def load(uri: str) -> bytes:
        return b"x" * 1000

    bot = TelegramBot("SECRET", load, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    mid = await bot.send_card(OWNER, build_card("post", POST, 1, 9), reply_to=3)
    assert mid == 5 and seen[0].url.path.endswith("/sendVideo") and b"reply_to_message_id" in seen[0].content
    assert b"inline_keyboard" in seen[0].content and "SECRET" not in repr(bot)
    big = TelegramBot("S", lambda _: _big(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await big.send_card(OWNER, build_card("post", POST, 1, 9))
    assert seen[-1].url.path.endswith("/sendMessage") and b"not+attached" in seen[-1].content


async def _big() -> bytes:
    return b"x" * 50_000_001


async def test_real_bot_parses_updates_and_raises_on_errors() -> None:
    updates = [
        {
            "update_id": 1,
            "callback_query": {
                "id": "c",
                "from": {"id": 42},
                "data": "r:1:ok",
                "message": {"message_id": 9, "chat": {"id": 42}},
            },
        },
        {"update_id": 2, "message": {"message_id": 3, "chat": {"id": 42}, "from": {"id": 42}, "text": "fix"}},
        {"update_id": 3, "edited_message": {}},
    ]

    def ok(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": updates})

    bot = TelegramBot("S", _big, client=httpx.AsyncClient(transport=httpx.MockTransport(ok)))
    got = await bot.get_updates(0, 0)
    assert [(u.kind, u.text) for u in got] == [("callback", "r:1:ok"), ("text", "fix"), ("ignored", "")]
    bad = TelegramBot(
        "S",
        _big,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(400, json={"ok": False, "description": "chat not found"})
            )
        ),
    )
    with pytest.raises(TelegramError, match="chat not found"):
        await bad.send_text(1, "x")
    _ = json
