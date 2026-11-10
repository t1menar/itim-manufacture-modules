"""Long-poll getUpdates with DB offset + idempotent update_id handling."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.db import repo
from review.observability.logging import get_logger
from review.telegram.real import RealTelegramBot, parse_update
from review.telegram.updates import TelegramUpdate

log = get_logger(__name__)

OFFSET_KEY = "telegram_getUpdates_offset"

UpdateHandler = Callable[[TelegramUpdate], Awaitable[None]]


class TelegramPoller:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        bot: RealTelegramBot,
        handler: UpdateHandler,
        *,
        long_poll_timeout: int = 25,
        allowed_chat_ids: set[int] | None = None,
    ) -> None:
        self._factory = factory
        self._bot = bot
        self._handler = handler
        self._timeout = long_poll_timeout
        self._allowed_chats = allowed_chat_ids
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="telegram-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("telegram_poll_loop_error")
                await asyncio.sleep(2.0)

    async def poll_once(self) -> int:
        async with self._factory() as s, s.begin():
            offset = await repo.get_bot_state_int(s, OFFSET_KEY)
        raw_updates = await self._bot.get_updates(offset=offset, long_poll_s=self._timeout)
        handled = 0
        max_id: int | None = None
        for raw in raw_updates:
            uid = raw.get("update_id")
            if isinstance(uid, int):
                max_id = uid if max_id is None else max(max_id, uid)
            upd = parse_update(raw)
            if upd is None:
                continue
            if self._allowed_chats is not None and upd.chat_id not in self._allowed_chats:
                log.info("telegram_update_chat_denied", chat_id=upd.chat_id, update_id=upd.update_id)
                continue
            async with self._factory() as s, s.begin():
                first = await repo.claim_telegram_update(s, upd.update_id)
            if not first:
                continue
            try:
                await self._handler(upd)
                handled += 1
            except Exception:
                log.exception("telegram_update_handler_failed", update_id=upd.update_id)
        if max_id is not None:
            async with self._factory() as s, s.begin():
                await repo.set_bot_state_int(s, OFFSET_KEY, max_id + 1)
        return handled
