from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mvideo.settings_model import VideoSettings

DIGEST = "sha256:" + "a" * 64
MINIMAL: dict[str, Any] = {
    "agent": {"image": f"video-agent@{DIGEST}"},
    "sandbox_images": {
        "postgres17": {
            "image": f"postgres:17@{DIGEST}",
            "ready_cmd": "pg_isready -U postgres",
            "version_cmd": "psql -U postgres -tAc 'SELECT version()'",
            "version_expect": "PostgreSQL 17.",
            "sessions": {"psql": {"kind": "psql", "start": "psql -X -U postgres -d {database}"}},
        }
    },
}


def info(client: TestClient) -> dict[str, Any]:
    resp = client.get("/info")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    return body


def test_info_document_shape(client: TestClient) -> None:
    body = info(client)
    assert body["contract"] == 1
    assert body["stages"] == ["video"]
    assert body["admin_endpoints"] == ["/admin/v1/runs", "/admin/v1/prompts", "/admin/v1/golden"]
    for key in ("settings_schema", "input_schema", "output_schema"):
        jsonschema.Draft202012Validator.check_schema(body[key])


def test_settings_schema_requires_agent_and_sandbox_images(client: TestClient) -> None:
    schema = info(client)["settings_schema"]
    assert sorted(schema["required"]) == ["agent", "sandbox_images"]
    assert schema["additionalProperties"] is False


def test_minimal_settings_validate_against_served_schema(client: TestClient) -> None:
    jsonschema.validate(MINIMAL, info(client)["settings_schema"])


def test_stage1_defaults() -> None:
    s = VideoSettings.model_validate(MINIMAL)
    assert s.agent.auth.mode == "subscription"
    assert s.agent.auth.credential_ref == "cred:claude-subscription"
    assert s.limits.job_budget_usd == 15
    assert (s.limits.max_jobs_per_day, s.limits.max_agent_runs_per_hour) == (6, 12)
    assert s.limits.steps["research"].max_turns == 60
    assert s.video.fps == 60
    assert s.video.safe_zone.model_dump() == {"top": 220, "bottom": 400, "left": 72, "right": 108}
    assert s.palette["accent"] == "#FF6B00"
    assert s.sources.allowed_repos[0].refs[0] == "REL_17_STABLE"


def test_cost_mode_follows_auth_mode() -> None:
    sub = VideoSettings.model_validate(MINIMAL)
    assert sub.resolved_cost_mode() == "estimate"
    key = VideoSettings.model_validate(
        {**MINIMAL, "agent": {**MINIMAL["agent"], "auth": {"mode": "api_key"}}}
    )
    assert key.resolved_cost_mode() == "usd"
    forced = VideoSettings.model_validate({**MINIMAL, "limits": {"cost_mode": "usd"}})
    assert forced.resolved_cost_mode() == "usd"


@pytest.mark.parametrize(
    "bad",
    [
        {**MINIMAL, "unknown_key": 1},
        {**MINIMAL, "agent": {"image": "video-agent:latest"}},  # not pinned by digest
        {**MINIMAL, "video": {"width": 720}},
        {**MINIMAL, "agent": {**MINIMAL["agent"], "auth": {"mode": "password"}}},
        {**MINIMAL, "limits": {"schema_retries": 9}},
        {"agent": MINIMAL["agent"]},  # sandbox_images missing
    ],
)
def test_invalid_settings_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VideoSettings.model_validate(bad)


JOB_INPUT: dict[str, Any] = {
    "idea_ref": {"id": 42, "rev": 1},
    "channels": [{"id": "itim", "language": "en", "name": "iTim", "settings": {"reading_wps": 3.5}}],
}


def test_input_schema_accepts_canonical_input(client: TestClient) -> None:
    jsonschema.validate(JOB_INPUT, info(client)["input_schema"])


def test_input_schema_requires_an_idea_ref_not_idea_text(client: TestClient) -> None:
    bad = {**{k: v for k, v in JOB_INPUT.items() if k != "idea_ref"}, "idea": {"id": 42, "text": "Why?"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, info(client)["input_schema"])


def test_output_schema_has_exactly_one_variant(client: TestClient) -> None:
    schema = info(client)["output_schema"]
    variants = schema["properties"]["variants"]
    assert (variants["minItems"], variants["maxItems"]) == (1, 1)
    assert set(schema["required"]) == {"variants", "provenance"}


def test_output_schema_requires_variant_metadata(client: TestClient) -> None:
    """D19 / C39: the core rejects a result without variants[].metadata (422 output_invalid)."""
    variant = info(client)["output_schema"]["$defs"]["Variant"]
    assert "metadata" in variant["required"]
    meta = info(client)["output_schema"]["$defs"]["Metadata"]
    assert set(meta["required"]) == {"title", "description", "topics", "platforms"}
    platform = info(client)["output_schema"]["$defs"]["PlatformMetadata"]
    assert set(platform["required"]) == {"caption", "hashtags"}
    assert platform["properties"]["hashtags"]["items"]["pattern"] == r"^#\S+$"
