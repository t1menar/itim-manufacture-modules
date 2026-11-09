from __future__ import annotations

import asyncio
import json
import os
import uuid

import aio_pika
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from publish.db.migrate import upgrade_head
from publish.db.session import session_factory
from publish.workers.amqp_consumer import AmqpConsumer

pytestmark = pytest.mark.skipif(
    not (os.getenv("PUBLISH_TEST_DATABASE_URL") and os.getenv("PUBLISH_TEST_AMQP_URL")),
    reason="PUBLISH_TEST_DATABASE_URL / PUBLISH_TEST_AMQP_URL not set",
)


@pytest.mark.asyncio
async def test_consumer_dedups_by_message_id() -> None:
    db = os.environ["PUBLISH_TEST_DATABASE_URL"]
    amqp = os.environ["PUBLISH_TEST_AMQP_URL"]
    queue_name = f"test.publish.{uuid.uuid4().hex[:8]}"
    upgrade_head(db)
    engine = create_async_engine(db)
    factory = session_factory(engine)
    consumer = AmqpConsumer(amqp, queue_name, factory)
    await consumer.start()
    for _ in range(50):
        if consumer.ready == "ok":
            break
        await asyncio.sleep(0.05)
    assert consumer.ready == "ok"

    conn = await aio_pika.connect_robust(amqp)
    ch = await conn.channel()
    await ch.declare_queue(queue_name, durable=True)
    body = json.dumps({"type": "job.requested", "payload": {}}).encode()
    mid = str(uuid.uuid4())
    for _ in range(2):
        await ch.default_exchange.publish(
            aio_pika.Message(body=body, message_id=mid, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=queue_name,
        )
    await asyncio.sleep(1.0)
    async with engine.connect() as c:
        n = (
            await c.execute(text("SELECT count(*) FROM amqp_inbox WHERE message_id = :id"), {"id": mid})
        ).scalar()
        assert n == 1
    await consumer.stop()
    await conn.close()
    await engine.dispose()
