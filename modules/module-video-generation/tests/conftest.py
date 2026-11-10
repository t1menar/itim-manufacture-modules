from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from mvgen.db import create_all, make_sessionmaker
from mvgen.models import Base


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """SQLite by default; set MVGEN_TEST_DATABASE_URL (postgresql+asyncpg://...) to run on Postgres."""
    url = os.environ.get("MVGEN_TEST_DATABASE_URL")
    if url:
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    await create_all(engine)
    yield make_sessionmaker(engine)
    await engine.dispose()
