"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncEngine

from review import __version__
from review.admin.allowlist import AdminAllowlist
from review.admin.registration import AdminRegistry
from review.api import admin, health, info, jobs
from review.api.jobs import install_auth_handler
from review.api.problems import install_problem_handlers
from review.bootstrap import BootstrapConfig, ConfigError
from review.clients.core import CoreClient
from review.db.session import make_engine, ping, session_factory
from review.jobs.flow import ReviewFlow
from review.jobs.service import JobService
from review.jobs.worker import Worker
from review.notify.handler import NotifyHandler
from review.observability.logging import get_logger
from review.observability.metrics import Metrics
from review.runtime_config import apply_overlay_to_bootstrap, load_runtime_overlay
from review.settings import SettingsHolder
from review.telegram.bot import TelegramBot
from review.telegram.factory import build_telegram_bot
from review.telegram.fake import FakeTelegramBot
from review.telegram.poller import TelegramPoller
from review.telegram.real import RealTelegramBot
from review.workers.amqp_consumer import AmqpConsumer

log = get_logger(__name__)


def create_app(
    config: BootstrapConfig,
    *,
    engine: AsyncEngine | None = None,
    migrate_on_start: bool = False,
    start_amqp: bool = True,
    start_worker: bool = True,
    bot: TelegramBot | None = None,
    load_db_secrets: bool = True,
) -> FastAPI:
    metrics = Metrics()
    settings_holder = SettingsHolder()
    own_engine = engine is None
    eng = engine or make_engine(config.database_url)
    factory = session_factory(eng)
    core = CoreClient(config.core_url, config.core_token)
    # Initial bot from env/bootstrap; may be replaced after DB overlay in lifespan.
    telegram = bot or _safe_build_bot(config)
    allowlist = AdminAllowlist(list(config.admin_telegram_ids))
    chat_ids = config.reviewer_chat_ids
    flow = ReviewFlow(
        factory,
        telegram,
        core,
        allowlist,
        chat_ids,
        s3_env_fallback=config.s3_env_fallback,
    )
    worker = Worker(factory, flow)
    job_service = JobService(factory, worker)
    notify_handler = NotifyHandler(factory, telegram, chat_ids)
    poller: TelegramPoller | None = None
    if isinstance(telegram, RealTelegramBot):
        poller = TelegramPoller(
            factory,
            telegram,
            flow.handle_update,
            allowed_chat_ids=set(chat_ids) if chat_ids else None,
        )
    consumer: AmqpConsumer | None = None
    if start_amqp and config.amqp_url:
        consumer = AmqpConsumer(
            config.amqp_url,
            config.amqp_queue,
            factory,
            notify_handler=notify_handler,
            job_service=job_service,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal telegram, allowlist, chat_ids, flow, worker, notify_handler, poller
        if migrate_on_start:
            from review.db.migrate import upgrade_head

            upgrade_head(config.database_url)
        if load_db_secrets and bot is None:
            try:
                overlay = await load_runtime_overlay(factory, config)
                effective = apply_overlay_to_bootstrap(config, overlay)
                telegram = build_telegram_bot(effective)
                allowlist = AdminAllowlist(list(overlay.admin_telegram_ids))
                chat_ids = overlay.reviewer_chat_ids
                registry: AdminRegistry | None = None
                if isinstance(telegram, RealTelegramBot):
                    registry = AdminRegistry(factory, overlay.admin_telegram_ids)
                    await registry.load()
                flow = ReviewFlow(
                    factory,
                    telegram,
                    core,
                    allowlist,
                    chat_ids,
                    s3_env_fallback=effective.s3_env_fallback,
                    registry=registry,
                )
                worker = Worker(factory, flow)
                if registry is not None:
                    registry.on_registered = worker.wake
                notify_handler = NotifyHandler(factory, telegram, chat_ids, registry)
                poller = None
                if isinstance(telegram, RealTelegramBot):
                    poller = TelegramPoller(
                        factory,
                        telegram,
                        flow.handle_update,
                        # With chat registration the flow decides who may talk to the bot.
                        allowed_chat_ids=None
                        if registry is not None
                        else (set(chat_ids) if chat_ids else None),
                    )
                app.state.config = effective
                app.state.telegram_bot = telegram
                app.state.notify_handler = notify_handler
                app.state.job_service = JobService(factory, worker)
                app.state.worker = worker
                app.state.flow = flow
                app.state.telegram_poller = poller
                log.info("runtime_config_loaded", telegram_mode=overlay.telegram_mode)
            except ConfigError:
                raise
            except Exception:
                # Tables may be absent in unit tests without migrate — keep env bootstrap.
                log.warning("runtime_config_db_skipped")
        if start_worker:
            worker.start(use_fake_poll=poller is None)
            if poller is not None:
                poller.start()
        if consumer is not None:
            await consumer.start()
        try:
            yield
        finally:
            if consumer is not None:
                await consumer.stop()
            if poller is not None:
                await poller.stop()
            if start_worker:
                await worker.stop()
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
    app.state.telegram_bot = telegram
    app.state.notify_handler = notify_handler
    app.state.job_service = job_service
    app.state.worker = worker
    app.state.flow = flow
    app.state.telegram_poller = poller
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


def _safe_build_bot(config: BootstrapConfig) -> TelegramBot:
    """Build from env; if real+missing token, Fake until DB overlay in lifespan."""
    if config.telegram_mode == "real" and not config.telegram_bot_token:
        return FakeTelegramBot()
    return build_telegram_bot(config)
