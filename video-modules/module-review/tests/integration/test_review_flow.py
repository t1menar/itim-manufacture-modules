"""Card → reject → reason → revise card reply → approve → publish notify reply."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import create_async_engine

from review.app import create_app
from review.bootstrap import BootstrapConfig
from review.db.migrate import upgrade_head
from review.db.session import session_factory
from review.intake import validate_job
from review.telegram.fake import FakeTelegramBot

pytestmark = pytest.mark.skipif(
    not os.getenv("REVIEW_TEST_DATABASE_URL"),
    reason="REVIEW_TEST_DATABASE_URL not set",
)


def _review_job(*, job_id: uuid.UUID, variant: uuid.UUID, round_n: int, callback: str) -> dict:
    return {
        "job_id": str(job_id),
        "attempt": 1,
        "fence": 1,
        "production_id": str(uuid.uuid4()),
        "stage": "review",
        "mode": "create" if round_n == 1 else "revise",
        "round": round_n,
        "variant": {"id": str(variant), "language": "en"},
        "input": {
            "idea_ref": {"id": 1, "rev": 1},
            "channels": [],
            "upstream": {
                "content_revision": {
                    "video": {"ref": f"s3://manufacture/v{round_n}.mp4", "sha256": "ab" * 32},
                    "metadata": {"title": f"Title v{round_n}", "description": "desc"},
                }
            },
        },
        "settings": {"version": 1, "values": {}},
        "credentials": [],
        "callback": {"base_url": callback},
        "deadline": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@pytest.mark.asyncio
@respx.mock
async def test_reject_revise_approve_notify_reply_chain() -> None:
    url = os.environ["REVIEW_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)
    bot = FakeTelegramBot()
    admin = 42
    config = BootstrapConfig(
        database_url=url,
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_review_test_token_xxxxxxxx",
        admin_telegram_ids=(admin,),
    )
    app = create_app(
        config,
        engine=engine,
        migrate_on_start=False,
        start_amqp=False,
        start_worker=False,
        bot=bot,
    )
    flow = app.state.flow
    service = app.state.job_service
    worker = app.state.worker
    notify = app.state.notify_handler

    variant = uuid.uuid4()
    job1 = uuid.uuid4()
    cb1 = f"http://core.test/internal/v1/jobs/{job1}"
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result_route = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))

    await service.accept(validate_job(_review_job(job_id=job1, variant=variant, round_n=1, callback=cb1)))
    await worker.run_once()
    await worker.drain()

    videos = [m for m in bot.sent if m.get("type") == "video"]
    assert len(videos) == 1
    assert videos[0]["reply_to_message_id"] is None
    assert "v1" in (videos[0].get("caption") or "")
    card1 = videos[0]["message_id"]

    # Reject → ask for reason
    bot.push_callback(chat_id=admin, user_id=admin, data=f"reject:{job1}", message_id=card1)
    for upd in bot.poll():
        await flow.handle_update(upd)
    asks = [m for m in bot.sent if m.get("type") == "message" and "Что не так" in (m.get("text") or "")]
    assert asks

    # Reason text
    bot.push_message(chat_id=admin, user_id=admin, text="плохой монтаж в начале")
    for upd in bot.poll():
        await flow.handle_update(upd)
    assert result_route.called
    body = result_route.calls.last.request.content
    assert b'"decision": "rejected"' in body or b'"decision":"rejected"' in body

    # New version after revise (round 2) — reply to previous card
    job2 = uuid.uuid4()
    cb2 = f"http://core.test/internal/v1/jobs/{job2}"
    result_route.reset()
    result_route.mock(return_value=httpx.Response(200, json={}))
    await service.accept(validate_job(_review_job(job_id=job2, variant=variant, round_n=2, callback=cb2)))
    await worker.run_once()
    await worker.drain()
    videos = [m for m in bot.sent if m.get("type") == "video"]
    assert len(videos) == 2
    assert videos[1]["reply_to_message_id"] == card1
    assert "v2" in (videos[1].get("caption") or "")
    card2 = videos[1]["message_id"]
    # Old markup marked stale
    assert any(m.get("type") == "edit_reply_markup" and m.get("message_id") == card1 for m in bot.sent)

    # Approve v2
    bot.push_callback(chat_id=admin, user_id=admin, data=f"approve:{job2}", message_id=card2)
    for upd in bot.poll():
        await flow.handle_update(upd)
    body = result_route.calls.last.request.content
    assert b'"decision": "approved"' in body or b'"decision":"approved"' in body

    # Publish notify replies to approved card
    before = len(bot.sent)
    async with session_factory(engine)() as session, session.begin():
        await notify.handle_http(
            session,
            {
                "notification_id": str(uuid.uuid4()),
                "status": "published",
                "attention_kind": "published",
                "variant_id": str(variant),
                "title": "Title v2",
                "channel": {"id": "itim", "name": "iTim", "language": "en"},
                "publications": [
                    {
                        "platform": "instagram",
                        "handle": "@itim",
                        "status": "published",
                        "url": "https://www.instagram.com/reel/ok/",
                    }
                ],
            },
        )
    pubs = [m for m in bot.sent[before:] if m.get("type") == "message"]
    assert pubs
    assert pubs[0]["reply_to_message_id"] == card2
    assert "Опубликовано" in pubs[0]["text"]
    assert "@itim" in pubs[0]["text"]

    # Slash admin commands are ignored by the review bot routing
    n_before = len(bot.sent)
    bot.push_message(chat_id=admin, user_id=admin, text="/module off vidmod")
    for upd in bot.poll():
        await flow.handle_update(upd)
    assert len(bot.sent) == n_before

    await engine.dispose()


@pytest.mark.asyncio
@respx.mock
async def test_no_admin_chat_fails_the_job_in_core() -> None:
    """Without an admin chat the run fails locally and core gets a blocked fail (no silent 7-day wait)."""
    url = os.environ["REVIEW_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)
    bot = FakeTelegramBot()
    config = BootstrapConfig(
        database_url=url,
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_review_test_token_xxxxxxxx",
        admin_telegram_ids=(),
    )
    app = create_app(
        config,
        engine=engine,
        migrate_on_start=False,
        start_amqp=False,
        start_worker=False,
        bot=bot,
    )
    flow = app.state.flow
    if flow._review_chat_id() != 0:  # a registered admin from another test run in the same DB
        pytest.skip("review DB already has a registered admin")
    job = uuid.uuid4()
    cb = f"http://core.test/internal/v1/jobs/{job}"
    fail_route = respx.post(f"{cb}/fail").mock(return_value=httpx.Response(200, json={}))
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    await app.state.job_service.accept(
        validate_job(_review_job(job_id=job, variant=uuid.uuid4(), round_n=1, callback=cb))
    )
    await app.state.worker.run_once()
    await app.state.worker.drain()
    assert not [m for m in bot.sent if m.get("type") == "video"]
    assert fail_route.called
    body = fail_route.calls.last.request.content
    assert b"no_admin" in body
    assert fail_route.calls.last.request.headers["X-Fence"] == "1"
    await engine.dispose()
