"""Normalized Telegram update used by Fake and Real bots."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    user_id: int
    text: str | None = None
    callback_data: str | None = None
    callback_message_id: int | None = None
    callback_query_id: str | None = None
    reply_to_message_id: int | None = None
