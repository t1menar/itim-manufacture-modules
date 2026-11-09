"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from mvideo import __version__
from mvideo.api import health, info
from mvideo.api.health import AuthStatus, Check
from mvideo.api.problems import install_problem_handlers
from mvideo.config import BootstrapConfig
from mvideo.observability.metrics import Metrics


async def _auth_unknown() -> str:
    # Replaced in phase B2 by a check that the credential named by agent.auth.credential_ref
    # is set and fetchable from the core.
    return "missing"


def create_app(
    config: BootstrapConfig,
    *,
    health_checks: list[Check] | None = None,
    ready_checks: list[Check] | None = None,
    auth_status: AuthStatus | None = None,
) -> FastAPI:
    app = FastAPI(title="module-video", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config
    app.state.metrics = Metrics()
    app.state.health_checks = health_checks if health_checks is not None else []
    app.state.ready_checks = ready_checks if ready_checks is not None else []
    app.state.auth_status = auth_status or _auth_unknown
    install_problem_handlers(app)
    app.include_router(info.router)
    app.include_router(health.router)
    return app
