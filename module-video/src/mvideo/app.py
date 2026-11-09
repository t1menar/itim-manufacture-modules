"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo import __version__
from mvideo.agents.prompts import PROMPTS_ROOT, PromptStore
from mvideo.api import admin_prompts, health, info, jobs, mcp_sandbox
from mvideo.api.health import AuthStatus, Check
from mvideo.api.problems import install_problem_handlers
from mvideo.config import BootstrapConfig
from mvideo.core_client import CoreGateway
from mvideo.db import prompts_repo
from mvideo.db.engine import db_health_check, session_factory
from mvideo.db.migrate import upgrade
from mvideo.db.repo import LEASE_TTL_S
from mvideo.ideas.relay import AmqpPublisher
from mvideo.ideas.runtime import IdeaRuntime
from mvideo.ideas.scheduler import SchedulerParams
from mvideo.observability.metrics import Metrics
from mvideo.pipeline.runner import AuthState, Finalize, Runner
from mvideo.pipeline.steps.base import Step
from mvideo.pipeline.worker import Worker
from mvideo.service import JobService
from mvideo.storage import Storage


def create_app(
    config: BootstrapConfig,
    *,
    engine: AsyncEngine | None = None,
    migrate_on_start: bool = False,
    storage: Storage | None = None,
    core: CoreGateway | None = None,
    steps: list[Step] | None = None,
    finalize: Finalize | None = None,
    worker_poll_s: float = 1.0,
    lease_renew_s: float = 20.0,
    cancel_poll_s: float = 2.0,
    health_checks: list[Check] | None = None,
    ready_checks: list[Check] | None = None,
    auth_status: AuthStatus | None = None,
    services: dict[str, Any] | None = None,
    revise_steps: list[Step] | None = None,
) -> FastAPI:
    auth = AuthState()
    worker: Worker | None = None
    runner: Runner | None = None
    service: JobService | None = None
    if (
        engine is not None
        and storage is not None
        and core is not None
        and steps is not None
        and finalize is not None
    ):
        factory = session_factory(engine)
        services = {"prompts": PromptStore(factory), **(services or {})}
        runner = Runner(
            factory=factory,
            storage=storage,
            core=core,
            steps=steps,
            finalize=finalize,
            owner=f"mvideo-{uuid.uuid4().hex[:8]}",
            auth_state=auth,
            lease_ttl_s=LEASE_TTL_S,
            lease_renew_s=lease_renew_s,
            cancel_poll_s=cancel_poll_s,
            services=services,
            revise_steps=revise_steps,
        )
        worker = Worker(factory=factory, runner=runner, poll_s=worker_poll_s, lease_ttl_s=LEASE_TTL_S)
        service = JobService(factory, worker, runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if engine is not None and migrate_on_start:
            await upgrade(engine)
            async with session_factory(engine)() as s, s.begin():
                await prompts_repo.seed_from_files(s, PROMPTS_ROOT)
        if worker is not None:
            worker.start()
        if idea_runtime is not None:
            idea_runtime.start()
        try:
            yield
        finally:
            if idea_runtime is not None:
                await idea_runtime.stop()
            if worker is not None:
                await worker.stop()
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
    idea_runtime: IdeaRuntime | None = None
    if engine is not None and config.amqp_url:
        idea_runtime = IdeaRuntime(
            session_factory(engine),
            AmqpPublisher(config.amqp_url, config.amqp_prefix),
            SchedulerParams(config.ideas_paused, config.ideas_max_dispatch, config.ideas_max_in_flight),
            tick_s=config.ideas_tick_s,
            amqp_url=config.amqp_url,
            prefix=config.amqp_prefix,
        )
    app.state.idea_runtime = idea_runtime
    app.state.config = config
    app.state.metrics = Metrics()
    app.state.engine = engine
    app.state.health_checks = list(health_checks or [])
    if engine is not None:
        app.state.health_checks.append(db_health_check(engine))
    app.state.ready_checks = ready_checks if ready_checks is not None else []
    app.state.auth_status = auth_status or auth.status
    app.state.service = service
    app.state.worker = worker
    app.state.runner = runner
    app.state.scratch = (services or {}).get("scratch")  # ScratchRegistry of the real capture step
    install_problem_handlers(app)
    app.include_router(info.router)
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(mcp_sandbox.router)
    app.include_router(admin_prompts.router)
    return app
