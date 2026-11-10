from __future__ import annotations

from fastapi.testclient import TestClient

from mvideo import __version__
from mvideo.app import create_app
from mvideo.config import BootstrapConfig


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_503_when_a_check_fails(config: BootstrapConfig) -> None:
    async def db_down() -> str:
        return "database_unreachable"

    resp = TestClient(create_app(config, health_checks=[db_down])).get("/health")
    assert resp.status_code == 503
    assert resp.json()["reasons"] == ["database_unreachable"]


def test_ready_reports_auth_and_never_fails_without_checks(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"ready": True, "auth": "missing"}


def test_ready_503_lists_reasons(config: BootstrapConfig) -> None:
    async def proxy_down() -> str:
        return "docker_proxy_unreachable"

    async def configured() -> str:
        return "configured"

    resp = TestClient(create_app(config, ready_checks=[proxy_down], auth_status=configured)).get("/ready")
    assert resp.status_code == 503
    assert resp.json() == {"ready": False, "auth": "configured", "reasons": ["docker_proxy_unreachable"]}


def test_metrics_exposes_build_info(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert f'video_build_info{{version="{__version__}"}} 1.0' in resp.text


def test_unknown_path_is_problem_json(client: TestClient) -> None:
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["type"].startswith("urn:manufacture:problem:")


def test_job_routes_need_a_bearer_token(client: TestClient) -> None:
    assert client.post("/v1/jobs", json={}).status_code == 401
