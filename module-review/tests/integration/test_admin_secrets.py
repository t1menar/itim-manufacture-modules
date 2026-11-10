"""Write-only secrets; dummy values must never appear in responses."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from review.app import create_app
from review.bootstrap import BootstrapConfig
from review.db.migrate import upgrade_head

pytestmark = pytest.mark.skipif(
    not os.getenv("REVIEW_TEST_DATABASE_URL"),
    reason="REVIEW_TEST_DATABASE_URL not set",
)

DUMMY = "dummy-telegram-bot-token-not-real"


def test_put_and_list_secret_hides_value() -> None:
    url = os.environ["REVIEW_TEST_DATABASE_URL"]
    upgrade_head(url)
    config = BootstrapConfig(
        database_url=url,
        listen_addr="127.0.0.1:8080",
        core_url="http://core.test",
        core_token="mft_review_test_token_xxxxxxxx",
        telegram_mode="fake",
    )
    app = create_app(config, migrate_on_start=False, start_amqp=False, start_worker=False)
    headers = {"Authorization": "Bearer mft_review_test_token_xxxxxxxx", "X-Actor": "test:admin"}
    with TestClient(app) as client:
        resp = client.put("/admin/v1/secrets/telegram.bot_token", headers=headers, json={"value": DUMMY})
        assert resp.status_code in (201, 204), resp.text
        assert DUMMY not in resp.text
        listed = client.get("/admin/v1/secrets", headers=headers)
        assert listed.status_code == 200
        assert DUMMY not in listed.text
        items = listed.json()["items"]
        row = next(i for i in items if i["key"] == "telegram.bot_token")
        assert row["present"] is True
        assert "value" not in row
