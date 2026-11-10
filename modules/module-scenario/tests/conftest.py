from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from mscenario.db import create_all, make_sessionmaker
from mscenario.models import Base

SOURCE = """\
int main(void)
{
    plan_query();
    return 0;
}
/* The planner picks a sequential scan when the table is small */
static void plan_query(void) { choose_scan(); }
"""


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """SQLite by default; set MSCENARIO_TEST_DATABASE_URL (postgresql+asyncpg://...) to run on Postgres."""
    url = os.environ.get("MSCENARIO_TEST_DATABASE_URL")
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
def repo(tmp_path: Path) -> str:
    """A real local git repository with one commit on `main`; returns its file:// URL."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.c").write_text(SOURCE)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    full = {**os.environ, **env}
    for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, env=full)
    return f"file://{root}"
