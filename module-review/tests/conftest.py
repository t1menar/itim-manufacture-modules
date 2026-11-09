from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from review.app import create_app
from review.bootstrap import BootstrapConfig


@pytest.fixture
def config() -> BootstrapConfig:
    return BootstrapConfig(
        database_url="postgresql+asyncpg://review:review@127.0.0.1:5432/review",
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_review_test_token_xxxxxxxx",
    )


@pytest.fixture
def client(config: BootstrapConfig) -> Iterator[TestClient]:
    # No real DB/AMQP in unit tests: pass a dummy engine path by skipping migrate/amqp
    # and overriding health checks.
    app = create_app(config, engine=None, migrate_on_start=False, start_amqp=False)
    # Avoid connecting: replace health checks and db_ready for unit scope.
    app.state.health_checks = []
    app.state.db_ready = "not_implemented"
    app.state.amqp_ready = "not_configured"
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_header(config: BootstrapConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.core_token}"}
