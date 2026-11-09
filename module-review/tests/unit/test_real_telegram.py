"""Real Telegram client against a local HTTP mock (respx) — never hits api.telegram.org."""

from __future__ import annotations

import httpx
import pytest
import respx

from review.telegram.real import (
    BOT_API_UPLOAD_LIMIT_BYTES,
    RealTelegramBot,
    TelegramAPIError,
    parse_update,
)

API = "https://telegram.test"


@pytest.fixture
def bot() -> RealTelegramBot:
    return RealTelegramBot("TEST_TOKEN_NOT_A_SECRET", api_base=API, max_retries=2, timeout_s=5.0)


@respx.mock
@pytest.mark.asyncio
async def test_send_video_and_answer_callback(bot: RealTelegramBot) -> None:
    respx.head("https://cdn.example/v.mp4").mock(
        return_value=httpx.Response(200, headers={"Content-Length": "1000"})
    )
    respx.post(f"{API}/botTEST_TOKEN_NOT_A_SECRET/sendVideo").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 7, "chat": {"id": 1}}},
        )
    )
    respx.post(f"{API}/botTEST_TOKEN_NOT_A_SECRET/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    sent = await bot.send_video(
        42,
        "https://cdn.example/v.mp4",
        caption="cap",
        reply_to_message_id=3,
        allow_sending_without_reply=True,
        reply_markup={"inline_keyboard": [[{"text": "Одобрить", "callback_data": "approve:x"}]]},
    )
    assert sent["message_id"] == 7
    await bot.answer_callback_query("cq-1", text="ok")
    assert respx.calls.call_count == 3
    send_video_req = next(c.request for c in respx.calls if c.request.url.path.endswith("/sendVideo"))
    assert b"allow_sending_without_reply" in send_video_req.content


@respx.mock
@pytest.mark.asyncio
async def test_429_then_success(bot: RealTelegramBot) -> None:
    route = respx.post(f"{API}/botTEST_TOKEN_NOT_A_SECRET/sendMessage")
    route.side_effect = [
        httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 0},
            },
        ),
        httpx.Response(200, json={"ok": True, "result": {"message_id": 9, "chat": {"id": 1}}}),
    ]
    out = await bot.send_message(1, "hi")
    assert out["message_id"] == 9


@respx.mock
@pytest.mark.asyncio
async def test_5xx_exhausted(bot: RealTelegramBot) -> None:
    respx.post(f"{API}/botTEST_TOKEN_NOT_A_SECRET/sendMessage").mock(
        return_value=httpx.Response(503, json={"ok": False})
    )
    with pytest.raises(TelegramAPIError):
        await bot.send_message(1, "hi")


@respx.mock
@pytest.mark.asyncio
async def test_large_video_falls_back_to_link(bot: RealTelegramBot) -> None:
    respx.head("https://cdn.example/big.mp4").mock(
        return_value=httpx.Response(200, headers={"Content-Length": str(BOT_API_UPLOAD_LIMIT_BYTES + 1)})
    )
    respx.post(f"{API}/botTEST_TOKEN_NOT_A_SECRET/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 11, "chat": {"id": 1}}})
    )
    out = await bot.send_video(5, "https://cdn.example/big.mp4", caption="title")
    assert out["message_id"] == 11
    assert b"sendVideo" not in respx.calls[1].request.url.path.encode()


def test_parse_callback_and_message() -> None:
    cb = parse_update(
        {
            "update_id": 10,
            "callback_query": {
                "id": "cq",
                "from": {"id": 7},
                "data": "approve:11111111-1111-1111-1111-111111111111",
                "message": {"message_id": 3, "chat": {"id": 99}},
            },
        }
    )
    assert cb is not None
    assert cb.callback_query_id == "cq"
    assert cb.chat_id == 99
    msg = parse_update(
        {
            "update_id": 11,
            "message": {
                "message_id": 4,
                "chat": {"id": 99},
                "from": {"id": 7},
                "text": "reason",
                "reply_to_message": {"message_id": 3},
            },
        }
    )
    assert msg is not None and msg.text == "reason" and msg.reply_to_message_id == 3


@respx.mock
@pytest.mark.asyncio
async def test_get_updates_offset() -> None:
    bot = RealTelegramBot("TOK", api_base=API, max_retries=1)
    respx.get(f"{API}/botTOK/getUpdates").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 5,
                        "message": {
                            "message_id": 1,
                            "chat": {"id": 1},
                            "from": {"id": 2},
                            "text": "hi",
                        },
                    }
                ],
            },
        )
    )
    updates = await bot.get_updates(offset=5, long_poll_s=0)
    assert len(updates) == 1
