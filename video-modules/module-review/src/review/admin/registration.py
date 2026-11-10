"""Single Telegram admin registered through the chat with a master token.

The master token is generated once (first start) and stored in ``module_secrets``
(``telegram.master_token``). Whoever sends it to the bot in a private chat becomes the one admin;
the registration is stored in ``module_settings`` (``telegram.registered_admin``) and survives restarts.
Registration is open only while no admin exists (neither registered nor configured by ids).
"""

# ruff: noqa: RUF001
from __future__ import annotations

import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.db.models import ModuleSecret, ModuleSetting
from review.db.secrets import get_secret, get_setting
from review.observability.logging import get_logger

log = get_logger(__name__)

SECRET_MASTER_TOKEN = "telegram.master_token"  # noqa: S105
SETTING_REGISTERED_ADMIN = "telegram.registered_admin"

MAX_FAILURES = 5
LOCKOUT_S = 15 * 60


class Outcome(Enum):
    NOT_ALLOWED = "not_allowed"  # an admin exists and this is someone else: stay silent
    ASK_TOKEN = "ask_token"  # noqa: S105
    REGISTERED = "registered"
    WRONG_TOKEN = "wrong_token"  # noqa: S105
    LOCKED = "locked"
    PRIVATE_ONLY = "private_only"


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    outcome: Outcome
    reply: str | None


class AdminRegistry:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        static_admin_ids: tuple[int, ...] = (),
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = factory
        self._static = frozenset(static_admin_ids)
        self._clock = clock
        self._token: str | None = None
        self._user_id: int | None = None
        self._chat_id: int | None = None
        self._failures: dict[int, list[float]] = {}
        self._seen_prompt: set[int] = set()
        self.on_registered: Callable[[], None] | None = None

    async def load(self) -> None:
        """Create the master token on the first start and load the registered admin."""
        async with self._factory() as s, s.begin():
            token = await get_secret(s, SECRET_MASTER_TOKEN)
            if token is None:
                token = secrets.token_urlsafe(24)
                s.add(ModuleSecret(key=SECRET_MASTER_TOKEN, value=token))
                created = True
            else:
                created = False
            admin = await get_setting(s, SETTING_REGISTERED_ADMIN)
        self._token = token
        if isinstance(admin, dict) and "user_id" in admin and "chat_id" in admin:
            self._user_id, self._chat_id = int(admin["user_id"]), int(admin["chat_id"])
        # The value itself is never logged.
        log.info("master_token_created" if created else "master_token_present", registered=self.registered)

    @property
    def registered(self) -> bool:
        return self._user_id is not None

    @property
    def open(self) -> bool:
        return not self.registered and not self._static

    @property
    def chat_id(self) -> int | None:
        return self._chat_id

    def is_admin(self, user_id: int) -> bool:
        return user_id == self._user_id or user_id in self._static

    async def handle(self, user_id: int, chat_id: int, text: str | None) -> RegistrationResult:
        """Answer a message of a user who is not an admin."""
        if not self.open:
            return RegistrationResult(Outcome.NOT_ALLOWED, None)
        if chat_id != user_id or chat_id <= 0:
            return RegistrationResult(
                Outcome.PRIVATE_ONLY, "Регистрация возможна только в личном чате с ботом."
            )
        now = self._clock()
        recent = [t for t in self._failures.get(user_id, []) if now - t < LOCKOUT_S]
        self._failures[user_id] = recent
        if len(recent) >= MAX_FAILURES:
            return RegistrationResult(Outcome.LOCKED, "Слишком много неверных попыток. Попробуйте позже.")
        candidate = (text or "").strip()
        first_contact = user_id not in self._seen_prompt
        self._seen_prompt.add(user_id)
        if (
            not candidate
            or candidate.startswith("/")
            or (first_contact and not self._looks_like_token(candidate))
        ):
            return RegistrationResult(
                Outcome.ASK_TOKEN, "Вы не зарегистрированы. Отправьте мастер-пароль одним сообщением."
            )
        if self._token is not None and hmac.compare_digest(candidate.encode(), self._token.encode()):
            await self._register(user_id, chat_id)
            return RegistrationResult(
                Outcome.REGISTERED,
                "Готово: вы зарегистрированы как администратор. Ролики на ревью будут приходить сюда.",
            )
        self._failures[user_id].append(now)
        return RegistrationResult(Outcome.WRONG_TOKEN, "Неверный мастер-пароль.")

    @staticmethod
    def _looks_like_token(text: str) -> bool:
        # A greeting or a question is not an attempt; do not count it as a failure.
        return " " not in text and len(text) >= 16

    async def _register(self, user_id: int, chat_id: int) -> None:
        async with self._factory() as s, s.begin():
            await self._put_setting(
                s,
                {"user_id": user_id, "chat_id": chat_id, "registered_at": datetime.now(UTC).isoformat()},
            )
        self._user_id, self._chat_id = user_id, chat_id
        self._failures.pop(user_id, None)
        log.info("admin_registered", user_id=user_id)
        if self.on_registered is not None:
            self.on_registered()

    @staticmethod
    async def _put_setting(session: AsyncSession, value: dict[str, object]) -> None:
        row = await session.get(ModuleSetting, SETTING_REGISTERED_ADMIN)
        if row is None:
            session.add(ModuleSetting(key=SETTING_REGISTERED_ADMIN, value=value))
        else:
            row.value = value
