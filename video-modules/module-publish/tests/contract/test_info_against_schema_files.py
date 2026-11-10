from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from fastapi.testclient import TestClient

from publish.app import create_app
from publish.bootstrap import BootstrapConfig

ROOT = Path(__file__).resolve().parents[2]


def test_info_schemas_match_files() -> None:
    cfg = BootstrapConfig(
        database_url="postgresql+asyncpg://x",
        listen_addr="127.0.0.1:9",
        core_url="http://core",
        core_token="tok",
    )
    app = create_app(cfg, migrate_on_start=False, start_amqp=False)
    app.state.health_checks = []
    app.state.db_ready = "not_implemented"
    with TestClient(app) as client:
        body = client.get("/info").json()
    for name, key in (
        ("settings.schema.json", "settings_schema"),
        ("input.schema.json", "input_schema"),
        ("output.schema.json", "output_schema"),
    ):
        on_disk = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        assert body[key] == on_disk
        jsonschema.Draft202012Validator.check_schema(on_disk)
