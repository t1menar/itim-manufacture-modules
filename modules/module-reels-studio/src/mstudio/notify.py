"""Short Telegram messages to the owner: started, paused for the usage limit, retrying, failed.

Only `sendMessage`: the review module owns `getUpdates`, so the two never compete for updates.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

log = logging.getLogger("mstudio.notify")


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...


class TelegramNotifier:
    def __init__(self, token: str, chats: tuple[int, ...]) -> None:
        self._token = token
        self._chats = chats

    def __repr__(self) -> str:
        return f"TelegramNotifier(chats={len(self._chats)})"  # never the token

    async def send(self, text: str) -> None:
        if not self._token or not self._chats:
            log.info("telegram not configured: %s", text)
            return
        async with httpx.AsyncClient(timeout=30) as c:
            for chat in self._chats:
                try:
                    r = await c.post(
                        f"https://api.telegram.org/bot{self._token}/sendMessage",
                        data={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"},
                    )
                    if r.status_code != 200:
                        log.warning("telegram sendMessage %s", r.status_code)
                except httpx.HTTPError as e:  # a notification must never break the job
                    log.warning("telegram sendMessage failed: %s", type(e).__name__)


class LogNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)
        log.info("notify: %s", text)
