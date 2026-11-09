"""Fixtures backed by a real PostgreSQL 17 (testcontainers). Skipped when Docker is unavailable."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from mvideo.db.engine import create_engine, session_factory
from mvideo.db.migrate import upgrade
from mvideo.db.models import Base

POSTGRES_IMAGE = "postgres:17"


async def _migrate(url: str) -> None:
    engine = create_engine(url)
    try:
        await upgrade(engine)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def pg_server() -> Iterator[str]:
    """URL of the maintenance database of a throw-away PostgreSQL 17 server."""
    try:
        container = PostgresContainer(POSTGRES_IMAGE, driver="asyncpg")
        container.start()
    except Exception as exc:  # Docker missing or image not pullable
        pytest.skip(f"PostgreSQL container unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest_asyncio.fixture
async def empty_db_url(pg_server: str) -> str:
    """A new, empty database on the server (for migration tests)."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(pg_server, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()
    return pg_server.rsplit("/", 1)[0] + "/" + name


@pytest.fixture(scope="session")
def migrated_url(pg_server: str) -> str:
    """The server's default database with all migrations applied, shared by repository tests."""
    asyncio.run(_migrate(pg_server))
    return pg_server


@pytest_asyncio.fixture
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(migrated_url)
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with eng.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as s:
        yield s
