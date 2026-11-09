from __future__ import annotations

import asyncio

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.db.engine import create_engine
from mvideo.db.migrate import upgrade
from mvideo.db.models import Base

TABLES = {
    "runs", "steps", "checks", "sandbox_runs", "agent_runs", "source_cache", "usage_log", "golden_runs",
    "prompt_versions", "prompt_active", "prompt_audit",
}  # fmt: skip


async def table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    return names - {"alembic_version"}


async def test_upgrade_head_on_empty_database(empty_db_url: str) -> None:
    engine = create_engine(empty_db_url)
    try:
        assert await table_names(engine) == set()
        await upgrade(engine)
        assert await table_names(engine) == TABLES
        async with engine.connect() as conn:
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert version == "0003"
    finally:
        await engine.dispose()


async def test_upgrade_is_repeatable(empty_db_url: str) -> None:
    engine = create_engine(empty_db_url)
    try:
        await upgrade(engine)
        await upgrade(engine)
        assert await table_names(engine) == TABLES
    finally:
        await engine.dispose()


async def test_concurrent_upgrades_do_not_collide(empty_db_url: str) -> None:
    """Two replicas starting together: the advisory lock serialises them."""
    engines = [create_engine(empty_db_url) for _ in range(4)]
    try:
        await asyncio.gather(*(upgrade(e) for e in engines))
        assert await table_names(engines[0]) == TABLES
    finally:
        for e in engines:
            await e.dispose()


async def test_models_match_migrated_schema(empty_db_url: str) -> None:
    """Fails when a model changes without a migration (or the other way round)."""
    engine = create_engine(empty_db_url)
    try:
        await upgrade(engine)
        async with engine.connect() as conn:
            diffs = await conn.run_sync(
                lambda c: compare_metadata(
                    MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata
                )
            )
        assert diffs == []
    finally:
        await engine.dispose()
