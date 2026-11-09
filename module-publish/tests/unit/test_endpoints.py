from __future__ import annotations

import jsonschema
from fastapi.testclient import TestClient

from publish import __version__


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_phase1(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["checks"]["settings"] == "defaults"
    assert body["checks"]["instagram"] == "not_implemented"


def test_info_contract(client: TestClient) -> None:
    resp = client.get("/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contract"] == 1
    assert body["stages"] == ["publish"]
    assert body["name"] == "Publish (Instagram, fake Login API)"
    assert body["version"] == __version__
    assert body["admin_endpoints"] == [
        "/admin/v1/accounts",
        "/admin/v1/ledger",
        "/admin/v1/dry-run",
    ]
    for key in ("settings_schema", "input_schema", "output_schema"):
        jsonschema.Draft202012Validator.check_schema(body[key])


def test_metrics(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert f'publish_build_info{{version="{__version__}"}} 1.0' in resp.text


def test_jobs_require_auth(client: TestClient) -> None:
    assert client.post("/v1/jobs", json={}).status_code == 401
    assert client.get("/v1/jobs/01900000-0000-7000-8000-000000000001").status_code == 401


def test_jobs_return_501_not_fake_success(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.post("/v1/jobs", headers=auth_header, json={"job_id": "x"})
    assert resp.status_code == 501
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "not_implemented"


def test_wrong_token_forbiddenish_unauthorized(client: TestClient) -> None:
    resp = client.post("/v1/jobs", headers={"Authorization": "Bearer wrong"}, json={})
    assert resp.status_code == 401


def test_unknown_is_problem(client: TestClient) -> None:
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
