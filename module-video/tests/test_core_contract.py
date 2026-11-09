"""What the module sends must satisfy the schemas the core validates (core/schemas, next to this module)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mvideo.agents.launcher import ReplayLauncher
from tests.test_steps import make_ctx

CORE = Path(__file__).resolve().parents[2] / "core" / "schemas"


def _validator(name: str) -> Draft202012Validator:
    path = CORE / name
    if not path.is_file():
        pytest.skip("core/schemas is not next to module-video")
    return Draft202012Validator(json.loads(path.read_text()))


def test_provenance_and_variant_of_the_real_result_match_the_core_schema(tmp_path: Path) -> None:
    from mvideo.pipeline.steps.media_steps import _provenance

    ctx = make_ctx(ReplayLauncher(tmp_path))
    from mvideo.agents.prompts import load_prompt

    ctx.prompt_cache["analysis"] = load_prompt("analysis", "1.0.0")
    provenance = _provenance(ctx)
    schema = _validator("stage-video-output.json")
    variant = {
        "language": "en",
        "video": {"ref": "s3://b/v.mp4", "sha256": "a" * 64, "duration_s": 120.5, "size": 123, "width": 1080,
                  "height": 1920, "fps": 30},
        "contact_sheet": "s3://b/sheet.jpg", "cover": "s3://b/cover.jpg",
        "post": {"caption": "c", "hashtags": ["#a"]},
        "metadata": {"title": "t", "description": "d", "topics": ["x"],
                     "platforms": {"instagram": {"caption": "c", "hashtags": ["#a"]}}},
        "checks": {},
    }  # fmt: skip
    errors = [e.message for e in schema.iter_errors({"variants": [variant], "provenance": provenance})]
    assert errors == []
