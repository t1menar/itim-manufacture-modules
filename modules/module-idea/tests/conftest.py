from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from midea.app import create_app
from midea.db import create_all, make_sessionmaker
from midea.models import Base


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """SQLite by default; set MIDEA_TEST_DATABASE_URL (postgresql+asyncpg://...) to run on Postgres."""
    url = os.environ.get("MIDEA_TEST_DATABASE_URL")
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


@pytest.fixture
async def session(sm: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sm() as s:
        yield s


@pytest.fixture
def app(sm: async_sessionmaker[AsyncSession]) -> FastAPI:
    return create_app(sessionmaker=sm, api_token="")


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
