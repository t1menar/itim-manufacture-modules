"""B6: a retry, a 5xx on media_publish or a timed-out run never posts the same reel twice."""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from publish.clients.core import CoreClient
from publish.db.migrate import upgrade_head
from publish.instagram.fake import FakeInstagramClient
from publish.intake import validate_job
from publish.jobs.runner import JobRunner
from publish.jobs.service import JobService
from publish.jobs.worker import Worker

pytestmark = pytest.mark.skipif(
    not os.getenv("PUBLISH_TEST_DATABASE_URL"),
    reason="PUBLISH_TEST_DATABASE_URL not set",
)


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime.now(dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ["PUBLISH_TEST_DATABASE_URL"]
    upgrade_head(url)
    eng = create_async_engine(url)
    # Runs left active by other tests would be picked up by this worker once the clock jumps.
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE runs SET status = 'cancelled' WHERE status IN ('accepted','running','cancelling')")
        )
    yield eng
    await eng.dispose()


def _stack(engine: AsyncEngine, ig: Any, clock: Clock) -> tuple[JobService, Worker]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    runner = JobRunner(factory=factory, core=CoreClient("http://core.test", "tok"), ig=ig, clock=clock)
    worker = Worker(factory=factory, runner=runner, clock=clock)
    return JobService(factory, worker, clock=clock), worker


def _job(
    *, job_id: uuid.UUID, intent: uuid.UUID, account: uuid.UUID, clock: Clock, fence: int = 1, try_: int = 1
) -> dict[str, Any]:
    return {
        "job_id": str(job_id),
        "attempt": try_,
        "try": try_,
        "fence": fence,
        "production_id": str(uuid.uuid4()),
        "stage": "publish",
        "mode": "create",
        "variant": {"id": str(uuid.uuid4()), "language": "en"},
        "input": {
            "idea_ref": {"id": 1, "rev": 1},
            "channels": [],
            "upstream": {
                "content_revision": {
                    "video": {"ref": "s3://manufacture/t/final.mp4", "sha256": "aa" * 32},
                    "metadata": {"platforms": {"instagram": {"caption": "cap", "hashtags": []}}},
                }
            },
            "intents": [
                {
                    "intent_id": str(intent),
                    "platform_account_id": str(account),
                    "content_revision_id": str(uuid.uuid4()),
                    "generation": 1,
                }
            ],
        },
        "settings": {"version": 1, "values": {}},
        "credentials": [],
        "callback": {"base_url": f"http://core.test/internal/v1/jobs/{job_id}"},
        "deadline": (clock.now + dt.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


async def _run(service: JobService, worker: Worker, body: dict[str, Any]) -> None:
    await service.accept(validate_job(body))
    await worker.run_once()
    await worker.drain()


def _pubs(call: Any) -> list[dict[str, Any]]:
    return json.loads(call.request.content)["output"]["publications"]


@pytest.mark.asyncio
@respx.mock
async def test_retry_after_successful_publish_does_not_post_twice(engine: AsyncEngine) -> None:
    clock = Clock()
    ig = FakeInstagramClient(dry_run=True)
    service, worker = _stack(engine, ig, clock)
    intent, account = uuid.uuid4(), uuid.uuid4()
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    # The post goes out, but core never gets the result (callback lost) → core retries the job.
    first = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(503))
    await _run(service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock))
    assert ig.publish_calls == 1
    original = _pubs(first.calls.last)[0]
    assert original["status"] == "published"

    first.mock(return_value=httpx.Response(200, json={}))
    retry_job = uuid.uuid4()
    await _run(service, worker, _job(job_id=retry_job, intent=intent, account=account, clock=clock, try_=2))
    assert ig.publish_calls == 1, "retry must not post again"
    assert len(ig.posts) == 1
    again = _pubs(first.calls.last)[0]
    assert again["status"] == "published"
    assert again["external_post_id"] == original["external_post_id"]
    assert again["url"] == original["url"]
    assert str(retry_job) in str(first.calls.last.request.url)


@pytest.mark.asyncio
@respx.mock
async def test_5xx_on_media_publish_reconciles_and_does_not_repost(engine: AsyncEngine) -> None:
    clock = Clock()
    ig = FakeInstagramClient(dry_run=True)
    ig.fail_next = "unknown_after_publish"  # posted, but media_publish answered 5xx
    service, worker = _stack(engine, ig, clock)
    intent, account = uuid.uuid4(), uuid.uuid4()
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))
    await _run(service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock))
    assert ig.publish_calls == 1
    pub = _pubs(result.calls.last)[0]
    assert pub["status"] == "published"  # found by reconcile, not by a second publish
    assert pub["external_post_id"] == ig.posts[0]["external_post_id"]

    await _run(
        service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock, try_=2)
    )
    assert ig.publish_calls == 1
    assert _pubs(result.calls.last)[0]["external_post_id"] == pub["external_post_id"]


@pytest.mark.asyncio
@respx.mock
async def test_unreconciled_unknown_is_never_reposted(engine: AsyncEngine) -> None:
    clock = Clock()
    ig = FakeInstagramClient(dry_run=True)
    ig.fail_next = "unknown"  # media_publish 5xx and the post is not found
    service, worker = _stack(engine, ig, clock)
    intent, account = uuid.uuid4(), uuid.uuid4()
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))
    await _run(service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock))
    assert _pubs(result.calls.last)[0]["status"] == "unknown"
    assert _pubs(result.calls.last)[0]["error_detail"]["code"] == "publish_outcome_unknown"
    calls = ig.publish_calls

    await _run(
        service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock, try_=2)
    )
    assert ig.publish_calls == calls, "unknown outcome is reconciled only, never re-posted"
    assert _pubs(result.calls.last)[0]["status"] == "unknown"


class SlowContainerIG(FakeInstagramClient):
    """The container takes so long that the job deadline passes before media_publish."""

    def __init__(self, clock: Clock, delay: dt.timedelta) -> None:
        super().__init__(dry_run=True)
        self.clock = clock
        self.delay = delay

    async def publish_reel(self, **kw: Any) -> Any:  # type: ignore[override]
        self.clock.now += self.delay
        return await super().publish_reel(**kw)


@pytest.mark.asyncio
@respx.mock
async def test_timed_out_run_cannot_post(engine: AsyncEngine) -> None:
    clock = Clock()
    ig = SlowContainerIG(clock, dt.timedelta(minutes=11))
    service, worker = _stack(engine, ig, clock)
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))
    fail = respx.post(url__regex=r".*/fail").mock(return_value=httpx.Response(200, json={}))
    intent, account = uuid.uuid4(), uuid.uuid4()
    await _run(service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock))
    assert ig.publish_calls == 0
    assert ig.posts == []
    assert not result.called
    assert json.loads(fail.calls.last.request.content)["details"]["code"] == "timeout"

    # The retry after the timeout may post (nothing went out), and does so exactly once.
    ig.delay = dt.timedelta(0)
    await _run(
        service, worker, _job(job_id=uuid.uuid4(), intent=intent, account=account, clock=clock, try_=2)
    )
    assert ig.publish_calls == 1


class SupersedingIG(FakeInstagramClient):
    """While the old fence is waiting for its container, core re-issues the job with fence 2."""

    def __init__(self, service: JobService | None = None, body: dict[str, Any] | None = None) -> None:
        super().__init__(dry_run=True)
        self.service = service
        self.body = body

    async def publish_reel(self, **kw: Any) -> Any:  # type: ignore[override]
        if self.service is not None and self.body is not None:
            body, self.body = self.body, None
            await self.service.accept(validate_job(body))
        return await super().publish_reel(**kw)


@pytest.mark.asyncio
@respx.mock
async def test_superseded_run_cannot_post(engine: AsyncEngine) -> None:
    clock = Clock()
    ig = SupersedingIG()
    service, worker = _stack(engine, ig, clock)
    respx.post(url__regex=r".*/progress").mock(return_value=httpx.Response(200, json={}))
    result = respx.post(url__regex=r".*/result").mock(return_value=httpx.Response(200, json={}))
    job_id, intent, account = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ig.service = service
    ig.body = _job(job_id=job_id, intent=intent, account=account, clock=clock, fence=2)
    await _run(service, worker, _job(job_id=job_id, intent=intent, account=account, clock=clock, fence=1))
    assert ig.publish_calls == 0  # fence 1 was fenced out right before media_publish
    await worker.run_once()
    await worker.drain()
    assert ig.publish_calls == 1
    assert result.calls.last.request.headers["X-Fence"] == "2"
