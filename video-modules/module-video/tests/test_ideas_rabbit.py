"""D21 against a real RabbitMQ (docker marker; skipped without Docker or the image rabbitmq:4-management)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import aio_pika
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.db.engine import session_factory
from mvideo.ideas import ids
from mvideo.ideas.relay import AmqpPublisher
from mvideo.ideas.runtime import IdeaRuntime
from mvideo.ideas.scheduler import SchedulerParams
from tests.test_ideas import PROD, queue, row, status_msg
from tests.test_sandbox import docker_client  # noqa: F401

pytestmark = pytest.mark.docker
IMAGE = "rabbitmq:4-management"


@pytest.fixture(scope="module")
def amqp_url(docker_client: Any) -> Iterator[str]:  # noqa: F811
    try:
        docker_client.images.get(IMAGE)
    except Exception:
        pytest.skip(f"image {IMAGE} is not present locally (docker pull {IMAGE})")
    box = docker_client.containers.run(
        IMAGE, detach=True, ports={"5672/tcp": None}, labels={"manufacture.test": "rabbit"}
    )
    try:
        box.reload()
        port = box.attrs["NetworkSettings"]["Ports"]["5672/tcp"][0]["HostPort"]
        yield f"amqp://guest:guest@127.0.0.1:{port}/"
    finally:
        box.remove(force=True)


async def connect(url: str) -> Any:
    for _ in range(60):
        try:
            return await aio_pika.connect_robust(url)
        except Exception:
            await asyncio.sleep(1)
    raise TimeoutError("RabbitMQ did not come up")


async def wait_for(cond: Any, seconds: float = 15) -> None:
    for _ in range(int(seconds * 10)):
        if await cond():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("condition not reached")


async def test_idea_ready_reaches_a_core_style_queue_and_statuses_come_back(
    amqp_url: str, engine: AsyncEngine
) -> None:
    factory = session_factory(engine)
    prefix = "t1."
    conn = await connect(amqp_url)
    ch = await conn.channel()
    events = await ch.declare_exchange(
        prefix + "manufacture.events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    core_queue = await ch.declare_queue(
        prefix + "core.job-events", durable=True
    )  # what core binds for idea.ready
    await core_queue.bind(events, routing_key="idea.ready")

    await queue(factory, 50, priority=5)
    runtime = IdeaRuntime(
        factory,
        AmqpPublisher(amqp_url, prefix),
        SchedulerParams(),
        tick_s=0.2,
        amqp_url=amqp_url,
        prefix=prefix,
    )
    runtime.start()
    try:
        msg = None
        for _ in range(100):
            msg = await core_queue.get(fail=False)
            if msg:
                break
            await asyncio.sleep(0.1)
        assert msg is not None, "idea.ready was not published"
        await msg.ack()
        env = json.loads(msg.body)
        assert msg.message_id == str(ids.ready_message_id(50, 1)) == env["message_id"]
        assert env["type"] == "idea.ready" and env["payload"]["idea_ref"] == {"id": 50, "rev": 1}
        assert (await row(factory, 50)).status == "dispatched"

        # core answers over the same exchange; the consumer applies it to the idea
        await events.publish(
            aio_pika.Message(status_msg(50, 1, "in_production", production=PROD)), "idea.in_production"
        )
        await events.publish(
            aio_pika.Message(status_msg(50, 1, "in_production", production=PROD)), "idea.in_production"
        )

        async def in_production() -> bool:
            return (await row(factory, 50)).status == "in_production"

        await wait_for(in_production)
        await events.publish(aio_pika.Message(status_msg(50, 1, "done", production=PROD)), "idea.done")

        async def done() -> bool:
            return (await row(factory, 50)).status == "done"

        await wait_for(done)
        assert await core_queue.get(fail=False) is None  # nothing was published twice
    finally:
        await runtime.stop()
        await conn.close()
