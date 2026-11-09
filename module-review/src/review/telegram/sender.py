"""Outbound message abstraction. Tests use FakeTelegramBot; real bot is out of scope."""

from __future__ import annotations

from typing import Protocol


class MessageSender(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None: ...
