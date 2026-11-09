"""Fake Telegram Bot API — no network. Records outbound messages for tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeTelegramUpdate:
    update_id: int
    chat_id: int
    user_id: int
    text: str | None = None
    callback_data: str | None = None
    callback_message_id: int | None = None
    reply_to_message_id: int | None = None


@dataclass
class FakeTelegramBot:
    sent: list[dict[str, Any]] = field(default_factory=list)
    _updates: list[FakeTelegramUpdate] = field(default_factory=list)
    _msg_seq: int = 0

    def _next_id(self) -> int:
        self._msg_seq += 1
        return self._msg_seq

    def push_message(
        self,
        *,
        chat_id: int,
        user_id: int,
        text: str,
        update_id: int = 1,
        reply_to_message_id: int | None = None,
    ) -> None:
        self._updates.append(
            FakeTelegramUpdate(
                update_id=update_id,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
        )

    def push_callback(
        self,
        *,
        chat_id: int,
        user_id: int,
        data: str,
        message_id: int,
        update_id: int = 1,
    ) -> None:
        self._updates.append(
            FakeTelegramUpdate(
                update_id=update_id,
                chat_id=chat_id,
                user_id=user_id,
                callback_data=data,
                callback_message_id=message_id,
            )
        )

    def poll(self) -> list[FakeTelegramUpdate]:
        out, self._updates = self._updates, []
        return out

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mid = self._next_id()
        msg = {
            "type": "message",
            "message_id": mid,
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": reply_to_message_id,
            "allow_sending_without_reply": allow_sending_without_reply,
            "reply_markup": reply_markup,
        }
        self.sent.append(msg)
        return msg

    async def send_video(
        self,
        chat_id: int,
        video: str,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mid = self._next_id()
        msg = {
            "type": "video",
            "message_id": mid,
            "chat_id": chat_id,
            "video": video,
            "caption": caption,
            "reply_to_message_id": reply_to_message_id,
            "allow_sending_without_reply": allow_sending_without_reply,
            "reply_markup": reply_markup,
        }
        self.sent.append(msg)
        return msg

    async def edit_message_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any] | None = None
    ) -> None:
        self.sent.append(
            {
                "type": "edit_reply_markup",
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            }
        )
