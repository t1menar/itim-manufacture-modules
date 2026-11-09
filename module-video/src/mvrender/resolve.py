"""Script + capture + source tree -> resolved scenario (`manufacture.resolved/1`).

Every capture reference is filled, every source line is attached verbatim and every `expect` is
checked. Misses raise typed errors (`capture_missing`, `expect_mismatch`, `source_missing`).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any, Protocol

from mvrender.scenario import RESOLVED_FORMAT

PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]{0,47})\}")


class ResolveError(Exception):
    code = "internal"


class CaptureMissing(ResolveError):
    code = "capture_missing"

    def __init__(self, name: str, where: str) -> None:
        self.name, self.where = name, where
        super().__init__(f"capture value {name!r} (used at {where}) is missing")


class ExpectMismatch(ResolveError):
    code = "expect_mismatch"

    def __init__(self, path: str, n: int, expect: str, actual: str | None) -> None:
        self.path, self.n, self.expect, self.actual = path, n, expect, actual
        super().__init__(f"{path}:{n} should contain {expect!r}, found {actual!r}")


class SourceMissing(ResolveError):
    code = "source_missing"

    def __init__(self, path: str, n: int | None = None) -> None:
        self.path, self.n = path, n
        super().__init__(f"source {path}" + (f" line {n}" if n else "") + " not found")


class SourceTree(Protocol):
    def exists(self, path: str) -> bool: ...
    def line(self, path: str, n: int) -> str | None: ...


def resolve(
    script: Mapping[str, Any], capture: Mapping[str, Any], source: SourceTree | None
) -> dict[str, Any]:
    doc = copy.deepcopy(dict(script))
    values = {k: str(v["value"]) for k, v in capture.get("values", {}).items()}
    commands: Mapping[str, Any] = capture.get("commands", {})
    paths: Mapping[str, str] = doc.get("sources", {})

    def fill(text: str, where: str) -> str:
        def sub(m: re.Match[str]) -> str:
            if m.group(1) not in values:
                raise CaptureMissing(m.group(1), where)
            return values[m.group(1)]

        return PLACEHOLDER.sub(sub, text)

    def value(v: dict[str, Any], where: str) -> dict[str, Any]:
        if "capture" in v:
            name = v["capture"]
            if name not in values:
                raise CaptureMissing(name, where)
            return {"text": f"{v.get('prefix', '')}{values[name]}{v.get('suffix', '')}"}
        return {"text": v["text"]}

    def src(alias: str, n: int, expect: str | None, where: str) -> str:
        path = paths.get(alias, alias)
        if source is None:
            raise SourceMissing(path)
        if not source.exists(path):
            raise SourceMissing(path)
        actual = source.line(path, n)
        if actual is None:
            raise SourceMissing(path, n)
        if expect and expect not in actual:
            raise ExpectMismatch(path, n, expect, actual)
        return actual

    def texts(node: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
        for k in keys:
            if isinstance(node.get(k), str):
                node[k] = fill(node[k], f"{where}/{k}")

    for si, scene in enumerate(doc["scenes"]):
        base = f"/scenes/{si}"
        for cap in scene.get("captions", []):
            cap["lines"] = [fill(x, f"{base}/captions") for x in cap["lines"]]
        for n in scene.get("notes", []):
            texts(n, ("term", "text"), f"{base}/notes")
        if scene.get("title"):
            scene["title"]["lines"] = [fill(x, f"{base}/title") for x in scene["title"]["lines"]]
            texts(scene["title"], ("footer",), f"{base}/title")
        for key in ("diagram", "panel"):
            d = scene.get(key)
            if not d:
                continue
            texts(d, ("heading", "footer"), f"{base}/{key}")
            for el in d["elements"]:
                texts(el, ("label", "name", "sub", "text"), f"{base}/{key}/{el['id']}")
                if "value" in el:
                    el["value"] = value(el["value"], f"{base}/{key}/{el['id']}")
                if el["type"] == "code_card":
                    el["path"] = paths.get(el["file"], el["file"])
                    el["rows"] = [
                        {"n": n, "text": src(el["file"], n, (el.get("expect") or {}).get(str(n)), el["id"])}
                        for n in el["lines"]
                    ]
        for ev in (scene.get("terminal") or {}).get("events", []):
            if "cmd" in ev:
                rec = commands.get(ev["cmd"])
                if rec is None:
                    raise CaptureMissing(ev["cmd"], f"{base}/terminal")
                out = ev.get("output") or {}
                ev["prompt"] = rec["prompt_before"]
                ev["prompt_after"] = rec["prompt_after"]
                ev["status"] = rec["status"]
                if out.get("hidden") or "lines" not in out:
                    ev["rows"] = []
                else:
                    a, b = out["lines"]
                    ev["rows"] = list(rec["output"][a : b + 1])
                ev["highlight"] = [fill(h, f"{base}/highlight") for h in out.get("highlight", [])]
            if "annotation" in ev:
                ev["annotation"] = [fill(x, f"{base}/annotation") for x in ev["annotation"]]
        for step in (scene.get("debugger") or {}).get("steps", []):
            texts(step, ("status",), f"{base}/{step['id']}")
            step["caption"] = [fill(x, f"{base}/{step['id']}") for x in step["caption"]]
            for n in step.get("notes", []):
                texts(n, ("term", "text"), f"{base}/{step['id']}/notes")
            for w in step.get("watch", []):
                w["value"] = value(w["value"], f"{base}/{step['id']}/watch")
            lines = (
                list(step.get("seq", []))
                + (step.get("loop") or {}).get("first", [])
                + (step.get("loop") or {}).get("rest", [])
            )
            for ln in lines:
                src(step["file"], ln["n"], ln.get("expect"), step["id"])
            step["rows"] = [
                {"n": n, "text": src(step["file"], n, None, step["id"])}
                for a, b in step["ranges"]
                for n in range(a, b + 1)
            ]
            step["path"] = paths.get(step["file"], step["file"])

    doc["format"] = RESOLVED_FORMAT
    doc["captures"] = values
    return doc
