"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo import __version__
from mvideo.api import health, info
from mvideo.api.health import AuthStatus, Check
from mvideo.api.problems import install_problem_handlers
from mvideo.config import BootstrapConfig
from mvideo.db.engine import db_health_check
from mvideo.db.migrate import upgrade
from mvideo.observability.metrics import Metrics


async def _auth_unknown() -> str:
    # Replaced in phase B2 by a check that the credential named by agent.auth.credential_ref
    # is set and fetchable from the core.
    return "missing"


def create_app(
    config: BootstrapConfig,
    *,
    engine: AsyncEngine | None = None,
    migrate_on_start: bool = False,
    health_checks: list[Check] | None = None,
    ready_checks: list[Check] | None = None,
    auth_status: AuthStatus | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if engine is not None and migrate_on_start:
            await upgrade(engine)
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(
        title="module-video",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.metrics = Metrics()
    app.state.engine = engine
    app.state.health_checks = list(health_checks or [])
    if engine is not None:
        app.state.health_checks.append(db_health_check(engine))
    app.state.ready_checks = ready_checks if ready_checks is not None else []
    app.state.auth_status = auth_status or _auth_unknown
    install_problem_handlers(app)
    app.include_router(info.router)
    app.include_router(health.router)
    return app
