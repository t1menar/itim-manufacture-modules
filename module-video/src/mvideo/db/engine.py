"""Async engine and session factory."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def db_health_check(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    """Health check for GET /health: None when the database answers, else a reason."""

    async def check() -> str | None:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return "database_unreachable"
        return None

    return check
