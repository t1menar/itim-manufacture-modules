"""Run Alembic migrations at start-up under a PostgreSQL advisory lock (03 section 7)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

# Fixed key so that every replica contends for the same lock ("mvideo" as an integer).
ADVISORY_LOCK_KEY = 0x6D766964


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return cfg


def _upgrade(connection: Connection, revision: str) -> None:
    cfg = alembic_config()
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, revision)
    connection.commit()


async def upgrade(engine: AsyncEngine, revision: str = "head") -> None:
    """Bring the schema to `revision`. Safe to call from several processes at once: the others
    wait on the lock, then find nothing left to do."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        try:
            await conn.commit()
            await conn.run_sync(_upgrade, revision)
        finally:
            await conn.rollback()
            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
            await conn.commit()
