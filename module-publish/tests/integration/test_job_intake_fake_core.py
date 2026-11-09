"""Accept → worker → Fake IG → result callback (Postgres required)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import create_async_engine

from publish.app import create_app
from publish.bootstrap import BootstrapConfig
from publish.db.migrate import upgrade_head
from publish.db.session import session_factory
from publish.instagram.fake import FakeInstagramClient
from publish.intake import validate_job

pytestmark = pytest.mark.skipif(
    not os.getenv("PUBLISH_TEST_DATABASE_URL"),
    reason="PUBLISH_TEST_DATABASE_URL not set",
)


def _job_body(*, job_id: uuid.UUID, account: uuid.UUID, intent: uuid.UUID, callback: str) -> dict:
    return {
        "job_id": str(job_id),
        "attempt": 1,
        "try": 1,
        "fence": 1,
        "production_id": str(uuid.uuid4()),
        "stage": "publish",
        "mode": "create",
        "variant": {"id": str(uuid.uuid4()), "language": "en"},
        "input": {
            "idea": {"id": 1, "text": "hello world idea", "language": "en"},
            "channels": [],
            "upstream": {
                "content_revision": {
                    "video": {
                        "ref": "s3://manufacture/t/final.mp4",
                        "sha256": "aa" * 32,
                    },
                    "metadata": {
                        "platforms": {"instagram": {"caption": "cap", "hashtags": ["#pg"]}}
                    },
                }
            },
            "intents": [
                {
                    "intent_id": str(intent),
                    "platform_account_id": str(account),
                    "content_revision_id": str(uuid.uuid4()),
                    "generation": 1,
                    "handle": "@itim",
                }
            ],
        },
        "settings": {"version": 1, "values": {}},
        "credentials": [],
        "callback": {"base_url": callback},
        "deadline": (datetime.now(UTC) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@pytest.mark.asyncio
@respx.mock
async def test_accept_run_publish_result_callback() -> None:
    url = os.environ["PUBLISH_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)
    factory = session_factory(engine)

    job_id = uuid.uuid4()
    account = uuid.uuid4()
    intent = uuid.uuid4()
    callback = f"http://core.test/internal/v1/jobs/{job_id}"
    progress = respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))

    config = BootstrapConfig(
        database_url=url,
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_publish_test_token_xxxxxxxx",
    )
    ig = FakeInstagramClient(dry_run=True)
    app = create_app(
        config,
        engine=engine,
        migrate_on_start=False,
        start_amqp=False,
        start_worker=False,
        ig_client=ig,
    )
    service = app.state.job_service
    worker = app.state.worker

    body = _job_body(job_id=job_id, account=account, intent=intent, callback=callback)
    job = validate_job(body)
    run = await service.accept(job)
    assert run.status == "accepted"

    claimed = await worker.run_once()
    assert claimed
    await worker.drain()

    assert result.called
    assert progress.called
    sent = result.calls.last.request
    assert sent.headers.get("X-Fence") == "1"
    payload = sent.content
    assert b'"status": "published"' in payload or b'"status":"published"' in payload
    assert ig.posts

    # Idempotent re-accept
    run2 = await service.accept(job)
    assert run2.job_id == run.job_id

    await engine.dispose()


@pytest.mark.asyncio
@respx.mock
async def test_unknown_outcome_reconcile_no_blind_resend() -> None:
    url = os.environ["PUBLISH_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)

    job_id = uuid.uuid4()
    account = uuid.uuid4()
    intent = uuid.uuid4()
    callback = f"http://core.test/internal/v1/jobs/{job_id}"
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))

    config = BootstrapConfig(
        database_url=url,
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_publish_test_token_xxxxxxxx",
    )
    ig = FakeInstagramClient(dry_run=True)
    ig.fail_next = "unknown"
    app = create_app(
        config,
        engine=engine,
        migrate_on_start=False,
        start_amqp=False,
        start_worker=False,
        ig_client=ig,
    )
    body = _job_body(job_id=job_id, account=account, intent=intent, callback=callback)
    await app.state.job_service.accept(validate_job(body))
    await app.state.worker.run_once()
    await app.state.worker.drain()
    assert result.called
    # Unknown → publications status unknown (reconcile miss); posts list empty (no blind second publish).
    assert b"publish_outcome_unknown" in result.calls.last.request.content
    assert ig.posts == []
    await engine.dispose()
