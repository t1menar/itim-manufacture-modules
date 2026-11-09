from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from publish.app import create_app
from publish.bootstrap import BootstrapConfig


@pytest.fixture
def config() -> BootstrapConfig:
    return BootstrapConfig(
        database_url="postgresql+asyncpg://publish:publish@127.0.0.1:5432/publish",
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_publish_test_token_xxxxxxxx",
    )


@pytest.fixture
def client(config: BootstrapConfig) -> Iterator[TestClient]:
    app = create_app(config, engine=None, migrate_on_start=False, start_amqp=False, start_worker=False)
    app.state.health_checks = []
    app.state.db_ready = "not_implemented"
    app.state.amqp_ready = "not_configured"
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_header(config: BootstrapConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.core_token}"}
