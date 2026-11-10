from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.app import create_app
from mvideo.config import BootstrapConfig
from mvideo.db.engine import create_engine


async def get(app, path: str) -> httpx.Response:  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


async def test_health_ok_when_database_answers(config: BootstrapConfig, engine: AsyncEngine) -> None:
    resp = await get(create_app(config, engine=engine), "/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_503_when_database_is_down(config: BootstrapConfig) -> None:
    dead = create_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    try:
        resp = await get(create_app(config, engine=dead), "/health")
    finally:
        await dead.dispose()
    assert resp.status_code == 503
    assert resp.json()["reasons"] == ["database_unreachable"]


async def test_startup_migrates_an_empty_database(config: BootstrapConfig, empty_db_url: str) -> None:
    engine = create_engine(empty_db_url)
    app = create_app(config, engine=engine, migrate_on_start=True)
    async with app.router.lifespan_context(app):
        check = create_engine(empty_db_url)
        try:
            async with check.connect() as conn:
                count = (await conn.execute(text("SELECT count(*) FROM runs"))).scalar_one()
        finally:
            await check.dispose()
    assert count == 0
