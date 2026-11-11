"""Telegram behind a Protocol. `TelegramBot` talks to the Bot API; tests use `FakeBot`."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from mtgr.cards import Card

log = logging.getLogger(__name__)
VIDEO_MAX_BYTES = 50_000_000  # Bot API limit for sendVideo uploads


@dataclass(frozen=True, slots=True)
class Update:
    update_id: int
    chat_id: int
    user_id: int
    kind: str  # callback | text
    text: str = ""  # callback data or message text
    callback_id: str | None = None
    message_id: int | None = None


class Bot(Protocol):
    async def send_card(self, chat_id: int, card: Card, reply_to: int | None = None) -> int: ...

    async def send_text(self, chat_id: int, text: str, reply_to: int | None = None) -> int: ...

    async def answer_callback(self, callback_id: str, text: str) -> None: ...

    async def clear_buttons(self, chat_id: int, message_id: int) -> None: ...

    async def get_updates(self, offset: int, timeout_s: int = 25) -> list[Update]: ...


class TelegramError(Exception):
    pass


class TelegramBot:
    """Bot API client. The token is held in the URL only and never logged or shown in `repr`."""

    def __init__(
        self,
        token: str,
        load: Callable[[str], Awaitable[bytes]],
        *,
        client: httpx.AsyncClient | None = None,
        base: str = "https://api.telegram.org",
    ) -> None:
        self._url = f"{base.rstrip('/')}/bot{token}"
        self._load, self._client = load, client

    def __repr__(self) -> str:
        return "TelegramBot(token=***)"

    async def _call(
        self, method: str, data: dict[str, Any], files: dict[str, Any] | None = None, timeout_s: float = 60.0
    ) -> Any:
        client = self._client or httpx.AsyncClient(timeout=timeout_s)
        try:
            for attempt in range(3):
                resp = await client.post(f"{self._url}/{method}", data=data, files=files)
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code == 429 and attempt < 2:
                    import asyncio  # noqa: PLC0415

                    await asyncio.sleep(float((body.get("parameters") or {}).get("retry_after", 1)))
                    continue
                if resp.status_code >= 500 and attempt < 2:
                    continue
                if resp.status_code != 200 or not body.get("ok"):
                    log.warning("telegram_error method=%s status=%s", method, resp.status_code)
                    raise TelegramError(f"{method}: {body.get('description', resp.status_code)}")
                return body["result"]
        finally:
            if self._client is None:
                await client.aclose()
        raise TelegramError(f"{method}: retries exhausted")

    @staticmethod
    def _markup(card: Card) -> str:
        import json  # noqa: PLC0415

        return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in card.buttons]]})

    async def send_card(self, chat_id: int, card: Card, reply_to: int | None = None) -> int:
        base: dict[str, Any] = {"chat_id": chat_id, "reply_markup": self._markup(card)}
        if reply_to:
            base["reply_to_message_id"] = reply_to
        if card.video:
            video = await self._load(card.video)
            if len(video) <= VIDEO_MAX_BYTES:
                caption = card.text if len(card.text) <= 1000 else card.text[:999] + "…"
                sent = await self._call(
                    "sendVideo", {**base, "caption": caption, "parse_mode": "HTML", "supports_streaming": "true"},
                    files={"video": ("post.mp4", video, "video/mp4")}, timeout_s=300.0,
                )  # fmt: skip
                if len(card.text) > 1000:  # the full card as a reply with the buttons
                    sent = await self._call(
                        "sendMessage",
                        {**base, "text": card.text, "parse_mode": "HTML", "reply_to_message_id": sent["message_id"]},
                    )
                return int(sent["message_id"])
            card = Card(card.text + "\n\n(video is over 50 MB: not attached)", None, None, card.buttons)
        sent = await self._call("sendMessage", {**base, "text": card.text, "parse_mode": "HTML"})
        return int(sent["message_id"])

    async def send_text(self, chat_id: int, text: str, reply_to: int | None = None) -> int:
        data: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to:
            data["reply_to_message_id"] = reply_to
        return int((await self._call("sendMessage", data))["message_id"])

    async def answer_callback(self, callback_id: str, text: str) -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def clear_buttons(self, chat_id: int, message_id: int) -> None:
        await self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": '{"inline_keyboard": []}'},
        )

    async def get_updates(self, offset: int, timeout_s: int = 25) -> list[Update]:
        raw = await self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout_s, "allowed_updates": '["message","callback_query"]'},
            timeout_s=timeout_s + 10.0,
        )
        out: list[Update] = []
        for u in raw:
            if cb := u.get("callback_query"):
                msg = cb.get("message") or {}
                out.append(
                    Update(
                        u["update_id"],
                        msg.get("chat", {}).get("id", 0),
                        cb["from"]["id"],
                        "callback",
                        cb.get("data", ""),
                        cb["id"],
                        msg.get("message_id"),
                    )  # fmt: skip
                )
            elif (m := u.get("message")) and m.get("text"):
                out.append(
                    Update(
                        u["update_id"],
                        m["chat"]["id"],
                        m.get("from", {}).get("id", 0),
                        "text",
                        m["text"],
                        None,
                        m["message_id"],
                    )
                )
            else:
                out.append(Update(u["update_id"], 0, 0, "ignored"))
        return out


@dataclass
class FakeBot:
    """In-memory bot recording everything it sends."""

    cards: list[tuple[int, Card, int | None]] = field(default_factory=list)
    texts: list[tuple[int, str, int | None]] = field(default_factory=list)
    answers: list[tuple[str, str]] = field(default_factory=list)
    cleared: list[tuple[int, int]] = field(default_factory=list)
    queue: list[Update] = field(default_factory=list)
    fail_sends: int = 0
    _mid: int = 100

    def _next(self) -> int:
        if self.fail_sends:
            self.fail_sends -= 1
            raise TelegramError("fake send failure")
        self._mid += 1
        return self._mid

    async def send_card(self, chat_id: int, card: Card, reply_to: int | None = None) -> int:
        mid = self._next()
        self.cards.append((chat_id, card, reply_to))
        return mid

    async def send_text(self, chat_id: int, text: str, reply_to: int | None = None) -> int:
        mid = self._next()
        self.texts.append((chat_id, text, reply_to))
        return mid

    async def answer_callback(self, callback_id: str, text: str) -> None:
        self.answers.append((callback_id, text))

    async def clear_buttons(self, chat_id: int, message_id: int) -> None:
        self.cleared.append((chat_id, message_id))

    async def get_updates(self, offset: int, timeout_s: int = 25) -> list[Update]:
        out = [u for u in self.queue if u.update_id >= offset]
        self.queue = []
        return out
