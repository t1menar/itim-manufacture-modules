"""Loads the reference scenario files and builds a matching in-memory source tree."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from mvideo.validate.source import MemorySource

REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "create_database"


def load(name: str) -> Any:
    return json.loads((REFERENCE / name).read_text(encoding="utf-8"))


def docs() -> dict[str, Any]:
    names = [
        "analysis.json",
        "research.json",
        "script.en.json",
        "capture.plan.json",
        "capture.json",
        "post.en.json",
    ]
    return {n: load(n) for n in names}


def fresh() -> dict[str, Any]:
    return copy.deepcopy(docs())


def synthetic_source(script: dict[str, Any], research: dict[str, Any]) -> MemorySource:
    """A source tree that holds exactly the lines the reference refers to (no Postgres needed)."""
    files: dict[str, dict[int, str]] = {}
    paths = script["sources"]

    def put(path: str, n: int, text: str) -> None:
        files.setdefault(path, {})[n] = "\t\t" + text

    for scene in script["scenes"]:
        for step in (scene.get("debugger") or {}).get("steps", []):
            lines = list(step.get("seq", []))
            loop = step.get("loop") or {}
            lines += loop.get("first", []) + loop.get("rest", [])
            for ln in lines:
                put(paths[step["file"]], ln["n"], f"x {ln['expect']} x")
        for key in ("diagram", "panel"):
            for el in (scene.get(key) or {}).get("elements", []):
                for num, exp in (el.get("expect") or {}).items():
                    put(paths[el["file"]], int(num), f"x {exp} x")
    for fact in research["facts"]:
        cite = fact["cite"]
        if "file" in cite:
            put(cite["file"], cite["line"], cite["quote"])
    for cp in research["call_path"]:
        for kl in cp.get("key_lines", []):
            put(cp["file"], kl["n"], kl["expect"])
    for path in paths.values():
        files.setdefault(path, {})
    return MemorySource(files)
