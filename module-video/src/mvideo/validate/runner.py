"""Validate a directory of step files: schema first, then the rules that need several files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mvideo.revise import check_changes
from mvideo.validate.issues import Issue, Report
from mvideo.validate.rules import RuleConfig, check_plan, check_research, check_script
from mvideo.validate.schemas import check_schema
from mvideo.validate.source import SourceTree

FILES = (
    "analysis.json",
    "research.json",
    "script.en.json",
    "capture.plan.json",
    "capture.json",
    "post.en.json",
    "blocked.json",
    "changes.en.json",
)


def validate_documents(
    docs: dict[str, Any],
    *,
    source: SourceTree | None = None,
    cfg: RuleConfig | None = None,
    previous_script: Any = None,
) -> Report:
    """Validate parsed documents given as `{file name: document}`; `previous_script` enables `revise_diff`."""
    cfg = cfg or RuleConfig()
    report = Report()
    schema_ok: dict[str, bool] = {}
    for name, doc in docs.items():
        report.checked.append(name)
        found = check_schema(doc, file=name)
        schema_ok[name] = not found
        report.extend(found)
    research = docs.get("research.json") if schema_ok.get("research.json") else None
    script = docs.get("script.en.json") if schema_ok.get("script.en.json") else None
    if research is not None:
        report.extend(check_research(research, source, cfg, "research.json"))
    if script is not None:
        report.extend(check_script(script, research=research, source=source, cfg=cfg))
        meta_commit = script["meta"]["system"]["commit"]
        if research is not None and research["commit"] != meta_commit:
            report.extend(
                [
                    Issue(
                        "schema",
                        "/commit",
                        "research commit differs from meta.system.commit",
                        "research.json",
                    )
                ]
            )
    changes = docs.get("changes.en.json")
    if (
        changes is not None
        and schema_ok.get("changes.en.json")
        and previous_script is not None
        and script is not None
    ):
        report.extend(check_changes(changes, previous_script, script))
    plan = docs.get("capture.plan.json")
    if plan is not None and schema_ok.get("capture.plan.json"):
        report.extend(check_plan(plan, script, cfg, "capture.plan.json"))
    return report


def validate_dir(
    directory: str | Path,
    *,
    source: SourceTree | None = None,
    cfg: RuleConfig | None = None,
) -> Report:
    """Validate every known file in `directory`; unreadable JSON is reported as a schema issue."""
    root = Path(directory)
    docs: dict[str, Any] = {}
    early: list[Issue] = []
    for name in FILES:
        path = root / name
        if not path.is_file():
            continue
        try:
            docs[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            early.append(Issue("schema", "/", f"cannot read JSON: {exc}", name))
    report = validate_documents(docs, source=source, cfg=cfg)
    report.issues[:0] = early
    return report
