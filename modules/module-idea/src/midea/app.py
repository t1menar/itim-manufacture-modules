"""FastAPI wiring and process configuration (environment variables, 12-factor)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from midea.api import register_errors, router
from midea.db import make_engine, make_sessionmaker


def create_app(
    *,
    database_url: str | None = None,
    api_token: str | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    token = api_token if api_token is not None else os.environ.get("MIDEA_API_TOKEN")
    engine = None
    if sessionmaker is None:
        url = database_url or os.environ["MIDEA_DATABASE_URL"]
        engine = make_engine(url)
        sessionmaker = make_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="module-idea", version="0.1.0", lifespan=lifespan)
    app.state.sessionmaker = sessionmaker
    app.state.api_token = token
    register_errors(app)
    app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
