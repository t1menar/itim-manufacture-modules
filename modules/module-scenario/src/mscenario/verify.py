"""Deterministic checks of the research output: schema, citations and cross-references. No tokens spent."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from mscenario.issues import Issue
from mscenario.sources import SourceTree

MEASUREMENT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s?(ms|msec|µs|us|s|sec|seconds|kb|mb|gb|kib|mib|gib|rows|tps|qps)\b", re.I
)
WS_RE = re.compile(r"\s+")


@cache
def _validator(name: str) -> Draft202012Validator:
    text = resources.files("mscenario.schemas").joinpath(f"{name}.schema.json").read_text()
    return Draft202012Validator(json.loads(text))


def schema_issues(name: str, doc: Any) -> list[Issue]:
    errors = sorted(_validator(name).iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [Issue("schema", "/" + "/".join(str(p) for p in e.absolute_path), e.message[:300]) for e in errors]


def norm(text: str) -> str:
    return WS_RE.sub(" ", text).strip()


def cite_key(cite: Mapping[str, Any]) -> str:
    """Identity of a citation: the same file, line and quote (or url and quote) is the same fact source."""
    if "file" in cite:
        raw = f"code|{cite['file']}|{cite['line']}|{norm(str(cite['quote']))}"
    else:
        raw = f"url|{cite['url']}|{norm(str(cite['quote']))}"
    return hashlib.sha256(raw.encode()).hexdigest()


def domain_allowed(url: str, allowed: Sequence[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return any(host == d or host.endswith("." + d) for d in (a.lower() for a in allowed))


def check_cite(
    cite: Mapping[str, Any],
    path: str,
    tree: SourceTree | None,
    allowed_domains: Sequence[str],
    url_quote_ok: Callable[[str, str], bool] | None = None,
) -> list[Issue]:
    if "file" in cite:
        if tree is None:
            return [Issue("research", path, "a code citation needs a pinned source tree, but this idea has none")]
        line = tree.line(str(cite["file"]), int(cite["line"]))
        if line is None:
            return [Issue("research", path, f"{cite['file']}:{cite['line']} does not exist at the pinned commit")]
        if norm(str(cite["quote"])) not in norm(line):
            return [
                Issue(
                    "research",
                    path,
                    f"quote not found on {cite['file']}:{cite['line']}; the line reads: {norm(line)[:120]!r}",
                )
            ]
        return []
    url = str(cite["url"])
    if not domain_allowed(url, allowed_domains):
        return [Issue("research", path, f"{urlparse(url).hostname} is not an allowed source domain")]
    if url_quote_ok is not None and not url_quote_ok(url, str(cite["quote"])):
        return [Issue("research", path, "the quote was not found on that page")]
    return []


def check_facts(
    facts: Sequence[Mapping[str, Any]],
    tree: SourceTree | None,
    allowed_domains: Sequence[str],
    url_quote_ok: Callable[[str, str], bool] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    for i, fact in enumerate(facts):
        base = f"/facts/{i}"
        issues += check_cite(fact["cite"], f"{base}/cite", tree, allowed_domains, url_quote_ok)
        if "url" in fact["cite"]:
            quote = norm(str(fact["cite"]["quote"]))
            for m in MEASUREMENT_RE.finditer(str(fact["text"])):
                if m.group(1) not in quote:  # a documented constant is in the quote; a measurement is not
                    issues.append(
                        Issue(
                            "research",
                            base,
                            f"{m.group(0)!r} is not in the quoted page text: a measurement is not a fact from a web "
                            "page, record it in capture_needs and measure it",
                        )
                    )
                    break
    return issues


def check_document(doc: Mapping[str, Any], tree: SourceTree | None) -> list[Issue]:
    """Cross references and call path against the source. Run on the assembled document."""
    issues: list[Issue] = []
    ids = [f["id"] for f in doc["facts"]]
    if len(set(ids)) != len(ids):
        issues.append(Issue("research", "/facts", "fact ids are not unique"))
    known = set(ids)
    for i, m in enumerate(doc["misconceptions"]):
        for fid in m["facts"]:
            if fid not in known:
                issues.append(Issue("research", f"/misconceptions/{i}/facts", f"unknown fact {fid}"))
    names = [c["name"] for c in doc["capture_needs"]]
    if len(set(names)) != len(names):
        issues.append(Issue("research", "/capture_needs", "capture need names are not unique"))
    terms = [t["term"].lower() for t in doc["terms"]]
    if len(set(terms)) != len(terms):
        issues.append(Issue("research", "/terms", "terms are not unique"))
    for i, step in enumerate(doc["call_path"]):
        base = f"/call_path/{i}"
        if step["line_end"] < step["line_start"]:
            issues.append(Issue("research", base, "line_end is before line_start"))
        if tree is None:
            issues.append(Issue("research", base, "call_path needs a pinned source tree"))
            continue
        if tree.line(step["file"], step["line_start"]) is None:
            issues.append(
                Issue("research", base, f"{step['file']}:{step['line_start']} does not exist at the pinned commit")
            )
        for j, kl in enumerate(step.get("key_lines", [])):
            text = tree.line(step["file"], kl["n"])
            if text is None or norm(kl["expect"]) not in norm(text):
                issues.append(
                    Issue(
                        "research",
                        f"{base}/key_lines/{j}",
                        f"{step['file']}:{kl['n']} does not contain {kl['expect']!r}",
                    )
                )
    return issues
