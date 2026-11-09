"""Immutable settings loaded from schemas/settings.schema.json defaults + Core snapshots."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


def load_settings_schema() -> dict[str, Any]:
    data = json.loads((SCHEMAS_DIR / "settings.schema.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("settings schema root must be an object")
    return cast(dict[str, Any], data)


def _defaults_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a nested defaults object from a Draft 2020-12 schema with defaults."""

    def walk(node: dict[str, Any]) -> Any:
        if "default" in node and "properties" not in node:
            return node["default"]
        props = node.get("properties")
        if isinstance(props, dict):
            out: dict[str, Any] = {}
            for key, child in props.items():
                if isinstance(child, dict):
                    if "default" in child and "properties" not in child:
                        out[key] = child["default"]
                    elif "properties" in child or child.get("type") == "object":
                        nested = walk(child)
                        out[key] = nested if nested is not None else child.get("default", {})
                    elif "default" in child:
                        out[key] = child["default"]
            if "default" in node and isinstance(node["default"], dict):
                merged = dict(node["default"])
                merged.update(out)
                return merged
            return out
        return node.get("default")

    result = walk(schema)
    return result if isinstance(result, dict) else {}


class Settings(BaseModel):
    """Typed view over settings.values. Extra keys from Core are ignored until schema bumps."""

    model_config = ConfigDict(extra="ignore")

    dry_run: bool = True
    instagram: dict[str, Any] = Field(default_factory=dict)
    reconcile: dict[str, Any] = Field(default_factory=dict)


class SettingsHolder:
    """Atomic swap of the current settings snapshot (version + values)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        schema = load_settings_schema()
        defaults = _defaults_from_schema(schema)
        self._version = 0
        self._settings = Settings.model_validate(defaults)
        self._source = "defaults"

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    @property
    def source(self) -> str:
        with self._lock:
            return self._source

    def get(self) -> Settings:
        with self._lock:
            return self._settings

    def replace(self, version: int, values: dict[str, Any], *, source: str) -> None:
        settings = Settings.model_validate(values)
        with self._lock:
            if version < self._version:
                return
            self._version = version
            self._settings = settings
            self._source = source
