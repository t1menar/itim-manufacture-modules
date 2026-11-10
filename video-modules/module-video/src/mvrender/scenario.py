"""Loading the scenario and the other documents the renderer reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCENARIO_FORMAT = "manufacture.scenario/1"
CAPTURE_FORMAT = "manufacture.capture/1"
RESOLVED_FORMAT = "manufacture.resolved/1"


class FormatError(ValueError):
    pass


def load_json(path: str | Path, expect_format: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != expect_format:
        got = doc.get("format") if isinstance(doc, dict) else type(doc).__name__
        raise FormatError(f"{path}: expected format {expect_format!r}, got {got!r}")
    return doc


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Load `script.en.json`; schema and rules are checked by `mvideo.validate`, not here."""
    return load_json(path, SCENARIO_FORMAT)


def load_capture(path: str | Path) -> dict[str, Any]:
    return load_json(path, CAPTURE_FORMAT)
