"""Create/patch publish accounts; dummy tokens only, never asserted as returned values."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from publish.app import create_app
from publish.bootstrap import BootstrapConfig
from publish.db.migrate import upgrade_head

pytestmark = pytest.mark.skipif(
    not os.getenv("PUBLISH_TEST_DATABASE_URL"),
    reason="PUBLISH_TEST_DATABASE_URL not set",
)

DUMMY = "dummy-ig-token-not-a-real-secret"


def _client() -> TestClient:
    url = os.environ["PUBLISH_TEST_DATABASE_URL"]
    upgrade_head(url)
    config = BootstrapConfig(
        database_url=url,
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_publish_test_token_xxxxxxxx",
    )
    app = create_app(config, migrate_on_start=False, start_amqp=False, start_worker=False)
    return TestClient(app)


def test_create_and_patch_account_hides_token() -> None:
    handle = f"@dummy-{uuid.uuid4().hex[:8]}"
    with _client() as client:
        headers = {"Authorization": "Bearer mft_publish_test_token_xxxxxxxx", "X-Actor": "test:admin"}
        resp = client.post(
            "/admin/v1/accounts",
            headers=headers,
            json={
                "channel_id": "itim",
                "platform": "instagram",
                "handle": handle,
                "external_id": "ig-user-dummy",
                "access_token": DUMMY,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["handle"] == handle
        assert body["external_id"] == "ig-user-dummy"
        assert body["has_token"] is True
        assert "access_token" not in body
        assert DUMMY not in resp.text
        acc_id = body["id"]

        resp = client.patch(
            f"/admin/v1/accounts/{acc_id}",
            headers=headers,
            json={"external_id": "ig-user-dummy-2", "enabled": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["external_id"] == "ig-user-dummy-2"
        assert body["enabled"] is False
        assert body["has_token"] is True
        assert DUMMY not in resp.text

        listed = client.get("/admin/v1/accounts", headers=headers)
        assert listed.status_code == 200
        assert DUMMY not in listed.text
        row = next(a for a in listed.json()["accounts"] if a["id"] == acc_id)
        assert row["has_token"] is True
        assert "access_token" not in row
