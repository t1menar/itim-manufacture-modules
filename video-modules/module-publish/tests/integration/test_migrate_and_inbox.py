from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from publish.db.inbox import try_claim
from publish.db.migrate import upgrade_head
from publish.db.session import session_factory

pytestmark = pytest.mark.skipif(
    not os.getenv("PUBLISH_TEST_DATABASE_URL"),
    reason="PUBLISH_TEST_DATABASE_URL not set",
)


@pytest.mark.asyncio
async def test_migrate_and_inbox_dedup() -> None:
    url = os.environ["PUBLISH_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)
    factory = session_factory(engine)
    mid = str(uuid.uuid4())
    async with factory() as s, s.begin():
        assert await try_claim(s, mid, "job.requested") is True
    async with factory() as s, s.begin():
        assert await try_claim(s, mid, "job.requested") is False
    async with engine.connect() as c:
        n = (
            await c.execute(text("SELECT count(*) FROM amqp_inbox WHERE message_id = :id"), {"id": mid})
        ).scalar()
        assert n == 1
    await engine.dispose()
