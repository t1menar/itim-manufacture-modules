"""JSON Schemas of every agent-written file (04 sections 4 to 7) and schema validation."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from mvideo.validate.issues import Issue

FORMAT_TO_SCHEMA = {
    "manufacture.scenario/1": "scenario",
    "manufacture.analysis/1": "analysis",
    "manufacture.research/1": "research",
    "manufacture.capture-plan/1": "capture-plan",
    "manufacture.capture/1": "capture",
    "manufacture.post/1": "post",
    "manufacture.blocked/1": "blocked",
    "manufacture.changes/1": "changes",
}

_formats = FormatChecker()


@_formats.checks("uri")
def _is_uri(value: object) -> bool:
    if not isinstance(value, str):
        return True
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


@cache
def load_schema(name: str) -> dict[str, Any]:
    text = resources.files("mvideo.validate").joinpath("schemas", f"{name}.schema.json").read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name), format_checker=_formats)


def all_schemas() -> dict[str, dict[str, Any]]:
    return {name: load_schema(name) for name in sorted(set(FORMAT_TO_SCHEMA.values()))}


def pointer(parts: Any) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def check_schema(doc: Any, *, file: str = "", name: str | None = None) -> list[Issue]:
    """Validate `doc` against the schema named by its `format` (or by `name`); one issue per error."""
    if name is None:
        fmt = doc.get("format") if isinstance(doc, dict) else None
        name = FORMAT_TO_SCHEMA.get(fmt) if isinstance(fmt, str) else None
        if name is None:
            return [Issue("schema", "/format", f"unknown or missing format {fmt!r}", file, fixable=True)]
    errors: list[ValidationError] = sorted(
        _validator(name).iter_errors(doc), key=lambda e: list(e.absolute_path)
    )
    return [Issue("schema", pointer(e.absolute_path), _short(e), file) for e in errors]


def _short(e: ValidationError) -> str:
    msg = e.message
    return msg if len(msg) <= 240 else msg[:237] + "..."
