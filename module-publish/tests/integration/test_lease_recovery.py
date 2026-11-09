from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from publish.db import repo
from publish.db.migrate import upgrade_head
from publish.db.repo import NewRun
from publish.db.session import session_factory

pytestmark = pytest.mark.skipif(
    not os.getenv("PUBLISH_TEST_DATABASE_URL"),
    reason="PUBLISH_TEST_DATABASE_URL not set",
)


@pytest.mark.asyncio
async def test_expired_lease_reclaimed() -> None:
    url = os.environ["PUBLISH_TEST_DATABASE_URL"]
    upgrade_head(url)
    engine = create_async_engine(url)
    factory = session_factory(engine)
    job_id = uuid.uuid4()
    async with factory() as s, s.begin():
        run, created = await repo.create_run(
            s,
            NewRun(
                job_id=job_id,
                attempt=1,
                fence=1,
                production_id=uuid.uuid4(),
                mode="create",
                settings_version=1,
                settings={},
                input={"intents": [{"intent_id": str(uuid.uuid4())}]},
                deadline=datetime.now(UTC) + timedelta(hours=1),
                callback_base_url="http://core.test/cb",
            ),
        )
        assert created
        # Simulate crash: mark running with expired lease
        run.status = "running"
        run.lease_owner = "dead-worker"
        run.lease_until = datetime.now(UTC) - timedelta(seconds=5)
    async with factory() as s, s.begin():
        claimed = await repo.claim_runs(s, "new-worker", limit=1)
        assert len(claimed) == 1
        assert claimed[0].job_id == job_id
        assert claimed[0].lease_owner == "new-worker"
    await engine.dispose()
