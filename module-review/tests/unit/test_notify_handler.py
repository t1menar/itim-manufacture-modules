from __future__ import annotations

import pytest

from review.notify.handler import NotifyHandler, format_notify_message
from review.telegram.fake import FakeTelegramBot


def test_format_notify_published() -> None:
    text = format_notify_message(
        {
            "status": "published",
            "attention_kind": "published",
            "title": "My reel",
            "publications": [
                {
                    "platform": "instagram",
                    "handle": "@itim",
                    "status": "published",
                    "url": "https://www.instagram.com/reel/x/",
                }
            ],
        }
    )
    assert "Опубликовано: My reel" in text
    assert "instagram @itim" in text
    assert "https://www.instagram.com/reel/x/" in text


def test_format_notify_error() -> None:
    text = format_notify_message(
        {
            "status": "failed",
            "attention_kind": "partial",
            "publications": [
                {
                    "platform": "instagram",
                    "status": "failed",
                    "error_detail": {"code": "rate_limited"},
                }
            ],
        }
    )
    assert "Публикация: partial/failed" in text
    assert "rate_limited" in text


@pytest.mark.asyncio
async def test_notify_handler_dedup_with_fake_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = FakeTelegramBot()
    claims: list[str] = []

    async def fake_claim(session, message_id: str, message_type: str) -> bool:
        if message_id in claims:
            return False
        claims.append(message_id)
        return True

    monkeypatch.setattr("review.notify.handler.try_claim", fake_claim)

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def begin(self):
            return self

    class _Factory:
        def __call__(self):
            return _Sess()

    handler = NotifyHandler(_Factory(), bot, (42, 7))  # type: ignore[arg-type]
    payload = {
        "notification_id": "01900000-0000-7000-8000-000000000001",
        "status": "partial",
        "attention_kind": "partial",
        "variant_id": "01900000-0000-7000-8000-000000000099",
        "publications": [{"platform": "instagram", "status": "failed", "error": "x"}],
    }
    r1 = await handler.handle("mid-1", payload)
    r2 = await handler.handle("mid-1", payload)
    assert r1.claimed and r1.sent == 2
    assert not r2.claimed and r2.sent == 0
    assert len(bot.sent) == 2
    assert "Публикация: partial/partial" in bot.sent[0]["text"]
