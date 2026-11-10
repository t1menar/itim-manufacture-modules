"""Loads the reference scenario files (a hand-made reference video) used by the renderer tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "create_database"


def load(name: str) -> Any:
    return json.loads((REFERENCE / name).read_text(encoding="utf-8"))
