"""Outbound message abstraction. Tests use FakeTelegramBot; real bot is out of scope for MVP routing."""

from __future__ import annotations

from typing import Any, Protocol


class MessageSender(Protocol):
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
