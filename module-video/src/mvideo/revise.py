"""Revise mode helpers (05 section 3, 04 section 7.3): diff, changes check, rendering, reuse tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mvideo.validate.issues import Issue


def _esc(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def structural_diff(old: Any, new: Any, base: str = "") -> dict[str, tuple[Any, Any]]:
    """`{JSON pointer: (before, after)}` for every leaf that changed.

    Objects recurse per key (an added or removed key is its own pointer); lists of equal length recurse per
    index; lists of different length are one change at the list pointer.
    """
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        out: dict[str, tuple[Any, Any]] = {}
        for k in sorted(set(old) | set(new)):
            p = f"{base}/{_esc(str(k))}"
            if k not in old or k not in new:
                out[p] = (old.get(k), new.get(k))
            else:
                out.update(structural_diff(old[k], new[k], p))
        return out
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        out = {}
        for i, (a, b) in enumerate(zip(old, new, strict=True)):
            out.update(structural_diff(a, b, f"{base}/{i}"))
        return out
    return {} if old == new else {base or "/": (old, new)}


def check_changes(
    changes: Mapping[str, Any],
    previous: Mapping[str, Any],
    script: Mapping[str, Any],
    file: str = "changes.en.json",
) -> list[Issue]:
    """`revise_diff`: the listed paths equal the structural diff of old and new script (exact)."""
    diff = structural_diff(previous, script)
    listed = [str(i["path"]) for i in changes.get("items", [])]
    issues = [
        Issue("revise_diff", p, "changed in the script but not listed in changes.items", file)
        for p in sorted(set(diff) - set(listed))
    ]
    issues += [
        Issue("revise_diff", p, "listed in changes.items but the script did not change there", file)
        for p in sorted(set(listed) - set(diff))
    ]
    issues += [
        Issue("revise_diff", p, "listed more than once", file)
        for p in sorted({x for x in listed if listed.count(x) > 1})
    ]
    for item in changes.get("items", []):
        p = str(item["path"])
        if p in diff and (item.get("before"), item.get("after")) != diff[p]:
            issues.append(
                Issue("revise_diff", p, "before/after differ from the actual old and new value", file)
            )
    return issues


def render_changes(changes: Mapping[str, Any], values_changed: list[str], limit: int) -> str:
    """`output.changes`: summary, a line per item, then "values changed" if any; cut to `limit` chars."""

    def short(v: Any) -> str:
        s = v if isinstance(v, str) else repr(v)
        return s if len(s) <= 60 else s[:57] + "..."

    lines = [str(changes["summary"])]
    lines += [
        f"{i['path']}: {short(i['before'])} → {short(i['after'])} ({i['why']})" for i in changes["items"]
    ]
    if values_changed:
        lines.append("values changed: " + ", ".join(values_changed))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def command_signature(script: Mapping[str, Any]) -> list[Any]:
    """Commands (id, text, session) and capture names: what decides whether the capture is reused."""
    from mvideo.sandbox.executor import script_commands

    cmds = sorted((k, v["text"], v["session"]) for k, v in script_commands(dict(script)).items())
    return [cmds, sorted((script.get("captures") or {}).keys())]


def hook_inputs(script: Mapping[str, Any]) -> list[Any]:
    """What the package agent reads for the post text: `meta.hook` and the captions of scene 0."""
    first = (script.get("scenes") or [{}])[0]
    return [script["meta"].get("hook"), first.get("captions")]


def values_changed(old: Mapping[str, Any], new: Mapping[str, Any], script: Mapping[str, Any]) -> list[str]:
    """Capture values that differ between two captures (only those used by the script are listed)."""
    a = {k: v["value"] for k, v in old.get("values", {}).items()}
    b = {k: v["value"] for k, v in new.get("values", {}).items()}
    return [
        f"{k}: {a[k]} → {b[k]}"
        for k in sorted(a.keys() & b.keys())
        if a[k] != b[k] and k in (script.get("captures") or {})
    ]
