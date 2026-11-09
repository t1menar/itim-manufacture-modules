"""Telegram bot abstraction. Real long-poll is selected by REVIEW_TELEGRAM_MODE."""

from __future__ import annotations

from typing import Any, Protocol


class TelegramBot(Protocol):
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def send_video(
        self,
        chat_id: int,
        video: str,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def edit_message_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any] | None = None
    ) -> None: ...

    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None: ...
