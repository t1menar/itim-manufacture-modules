"""Admin registration in the chat with the master token (one admin, cards wait for the admin)."""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
import respx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration.test_review_flow import _review_job

from review.admin.allowlist import AdminAllowlist
from review.admin.registration import SECRET_MASTER_TOKEN, SETTING_REGISTERED_ADMIN, AdminRegistry
from review.clients.core import CoreClient
from review.db.migrate import upgrade_head
from review.db.models import ModuleSecret, ModuleSetting
from review.db.secrets import get_secret
from review.db.session import session_factory
from review.intake import validate_job
from review.jobs.flow import ReviewFlow
from review.jobs.service import JobService
from review.jobs.worker import Worker
from review.telegram.fake import FakeTelegramBot

pytestmark = pytest.mark.skipif(
    not os.getenv("REVIEW_TEST_DATABASE_URL"),
    reason="REVIEW_TEST_DATABASE_URL not set",
)


async def _setup(static: tuple[int, ...] = ()):  # type: ignore[no-untyped-def]
    url = os.environ["REVIEW_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)
    factory = session_factory(engine)
    async with factory() as s, s.begin():
        await s.execute(delete(ModuleSecret).where(ModuleSecret.key == SECRET_MASTER_TOKEN))
        await s.execute(delete(ModuleSetting).where(ModuleSetting.key == SETTING_REGISTERED_ADMIN))
    bot = FakeTelegramBot()
    registry = AdminRegistry(factory, static)
    await registry.load()
    flow = ReviewFlow(
        factory, bot, CoreClient("http://core.test", "mft_review_test_token_xxxxxxxx"),
        AdminAllowlist([]), (), registry=registry,
    )  # fmt: skip
    worker = Worker(factory, flow)
    registry.on_registered = worker.wake
    return factory, bot, registry, flow, worker, JobService(factory, worker)


async def _say(flow: ReviewFlow, bot: FakeTelegramBot, user: int, text: str, chat: int | None = None) -> None:
    bot.push_message(chat_id=chat or user, user_id=user, text=text)
    for upd in bot.poll():
        await flow.handle_update(upd)


def _texts(bot: FakeTelegramBot) -> list[str]:
    return [m.get("text") or "" for m in bot.sent if m.get("type") == "message"]


@pytest.mark.asyncio
@respx.mock
async def test_master_token_registers_one_admin_and_pending_card_is_sent() -> None:
    factory, bot, registry, flow, worker, service = await _setup()
    async with factory() as s:
        token = await get_secret(s, SECRET_MASTER_TOKEN)
    assert token and len(token) >= 24
    again = AdminRegistry(factory)
    await again.load()  # generated once: the second start keeps the same value
    async with factory() as s:
        assert await get_secret(s, SECRET_MASTER_TOKEN) == token

    # a job arrives before anybody registered: nothing is sent, nothing fails
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    job = uuid.uuid4()
    await service.accept(
        validate_job(
            _review_job(
                job_id=job,
                variant=uuid.uuid4(),
                round_n=1,
                callback=f"http://core.test/internal/v1/jobs/{job}",
            )
        )
    )
    assert await worker.run_once() == []
    assert not [m for m in bot.sent if m.get("type") == "video"]

    await _say(flow, bot, 7, "hello")
    assert "мастер-пароль" in _texts(bot)[-1]
    await _say(flow, bot, 7, "x" * 24)
    assert "Неверный" in _texts(bot)[-1]
    assert not registry.registered

    await _say(flow, bot, 7, token)
    assert registry.registered and registry.is_admin(7) and registry.chat_id == 7
    assert "зарегистрированы" in _texts(bot)[-1]

    # the waiting card is delivered to the new admin
    assert len(await worker.run_once()) == 1
    await worker.drain()
    videos = [m for m in bot.sent if m.get("type") == "video"]
    assert len(videos) == 1 and videos[0]["chat_id"] == 7

    # registration survives a restart; a second person cannot register even with the token
    restarted = AdminRegistry(factory)
    await restarted.load()
    assert restarted.is_admin(7) and not restarted.open
    sent_before = len(bot.sent)
    await _say(flow, bot, 8, token)
    assert not registry.is_admin(8) and registry.chat_id == 7
    assert len(bot.sent) == sent_before  # silence for everybody else


@pytest.mark.asyncio
async def test_lockout_after_wrong_attempts_and_groups_are_refused() -> None:
    _, bot, registry, flow, _, _ = await _setup()
    await _say(flow, bot, 9, "hi")
    for _ in range(5):
        await _say(flow, bot, 9, "y" * 30)
    await _say(flow, bot, 9, "z" * 30)
    assert "Слишком много" in _texts(bot)[-1]
    await _say(flow, bot, 10, "t" * 30, chat=-1001)
    assert "личном чате" in _texts(bot)[-1]
    assert not registry.registered


@pytest.mark.asyncio
async def test_configured_admin_ids_disable_registration() -> None:
    _, bot, registry, flow, _, _ = await _setup(static=(42,))
    assert not registry.open and registry.is_admin(42)
    await _say(flow, bot, 5, "anything")
    assert _texts(bot) == []
