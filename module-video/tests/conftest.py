from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mvideo.app import create_app
from mvideo.config import BootstrapConfig

ENV = {
    "VIDEO_DATABASE_URL": "postgresql+asyncpg://video:pw@postgres:5432/video",
    "VIDEO_LISTEN_ADDR": "0.0.0.0:8080",
    "MODULE_CORE_URL": "http://core:8080/",
    "MODULE_CORE_TOKEN": "test-token",
    "S3_ENDPOINT": "http://minio:9000",
    "S3_ACCESS_KEY": "access",
    "S3_SECRET_KEY": "secret",
    "S3_BUCKET": "manufacture",
    "DOCKER_HOST": "tcp://video-docker-proxy:2375",
    "VIDEO_AGENT_NETWORK": "video-agents",
}


@pytest.fixture
def env() -> dict[str, str]:
    return dict(ENV)


@pytest.fixture
def config(env: dict[str, str]) -> BootstrapConfig:
    return BootstrapConfig.from_env(env)


@pytest.fixture
def client(config: BootstrapConfig) -> TestClient:
    return TestClient(create_app(config))


pytest_plugins = ["tests.conftest_db"]
