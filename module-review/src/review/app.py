"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncEngine

from review import __version__
from review.api import admin, health, info, jobs
from review.api.jobs import install_auth_handler
from review.api.problems import install_problem_handlers
from review.bootstrap import BootstrapConfig
from review.clients.core import CoreClient
from review.db.session import make_engine, ping, session_factory
from review.notify.handler import NotifyHandler
from review.observability.logging import get_logger
from review.observability.metrics import Metrics
from review.settings import SettingsHolder
from review.telegram.fake import FakeTelegramBot
from review.workers.amqp_consumer import AmqpConsumer

log = get_logger(__name__)


def create_app(
    config: BootstrapConfig,
    *,
    engine: AsyncEngine | None = None,
    migrate_on_start: bool = False,
    start_amqp: bool = True,
) -> FastAPI:
    metrics = Metrics()
    settings_holder = SettingsHolder()
    own_engine = engine is None
    eng = engine or make_engine(config.database_url)
    factory = session_factory(eng)
    core = CoreClient(config.core_url, config.core_token)
    bot = FakeTelegramBot()
    notify_handler = NotifyHandler(factory, bot, config.admin_telegram_ids)
    consumer: AmqpConsumer | None = None
    if start_amqp and config.amqp_url:
        consumer = AmqpConsumer(config.amqp_url, config.amqp_queue, factory, notify_handler=notify_handler)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if migrate_on_start:
            from review.db.migrate import upgrade_head

            upgrade_head(config.database_url)
        if consumer is not None:
            await consumer.start()
        try:
            yield
        finally:
            if consumer is not None:
                await consumer.stop()
            if own_engine:
                await eng.dispose()

    app = FastAPI(
        title="module-review",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.metrics = metrics
    app.state.settings_holder = settings_holder
    app.state.engine = eng
    app.state.core = core
    app.state.session_factory = factory
    app.state.telegram_bot = bot
    app.state.notify_handler = notify_handler
    app.state.amqp_consumer = consumer
    app.state.db_ready = "ok"
    app.state.amqp_ready = "not_configured" if consumer is None else "starting"
    app.state.health_checks = []

    async def _db_check() -> str | None:
        reason = await ping(eng)
        app.state.db_ready = "ok" if reason is None else "error"
        return reason

    app.state.health_checks.append(_db_check)

    install_problem_handlers(app)
    install_auth_handler(app)
    app.include_router(info.router)
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(admin.router)

    metrics_router = APIRouter()

    @metrics_router.get("/metrics")
    async def metrics_endpoint(request: Request) -> Response:
        if consumer is not None:
            request.app.state.amqp_ready = consumer.ready
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type)

    app.include_router(metrics_router)

    return app
