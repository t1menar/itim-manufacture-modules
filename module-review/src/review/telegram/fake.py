"""Fake Telegram Bot API — no network. Records outbound messages for tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeTelegramUpdate:
    update_id: int
    chat_id: int
    user_id: int
    text: str


@dataclass
class FakeTelegramBot:
    sent: list[dict[str, Any]] = field(default_factory=list)
    _updates: list[FakeTelegramUpdate] = field(default_factory=list)

    def push_message(self, *, chat_id: int, user_id: int, text: str, update_id: int = 1) -> None:
        self._updates.append(
            FakeTelegramUpdate(update_id=update_id, chat_id=chat_id, user_id=user_id, text=text)
        )

    def poll(self) -> list[FakeTelegramUpdate]:
        out, self._updates = self._updates, []
        return out

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append({"chat_id": chat_id, "text": text})
