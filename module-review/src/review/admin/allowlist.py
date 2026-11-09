"""Telegram admin allowlist (D20)."""

from __future__ import annotations


class AdminAllowlist:
    def __init__(self, telegram_user_ids: list[int]) -> None:
        self._ids = set(telegram_user_ids)

    def contains(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self._ids
