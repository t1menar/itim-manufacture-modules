from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from mvideo.cli import validate_main
from mvideo.validate.rules import RuleConfig
from mvideo.validate.runner import validate_dir, validate_documents
from mvideo.validate.schemas import all_schemas, load_schema
from mvideo.validate.source import DirSource
from tests import refdata

REAL_SOURCE = Path(__file__).resolve().parents[2] / "create-database-video" / "pgsrc17"


def run(docs: dict[str, Any], cfg: RuleConfig | None = None) -> set[str]:
    """Validate mutated documents against the source tree of the pristine reference."""
    pristine = refdata.docs()
    src = refdata.synthetic_source(pristine["script.en.json"], pristine["research.json"])
    return validate_documents(copy.deepcopy(docs), source=src, cfg=cfg).rules()


def test_all_schemas_are_valid_json_schemas() -> None:
    from jsonschema import Draft202012Validator

    names = all_schemas()
    assert {
        "scenario",
        "analysis",
        "research",
        "capture-plan",
        "capture",
        "post",
        "blocked",
        "changes",
    } <= set(names)
    for name in names:
        Draft202012Validator.check_schema(load_schema(name))


def test_reference_files_pass_everything() -> None:
    docs = refdata.docs()
    src = refdata.synthetic_source(docs["script.en.json"], docs["research.json"])
    report = validate_documents(docs, source=src)
    assert report.ok, "\n".join(map(str, report.issues))
    assert len(report.checked) == 6


@pytest.mark.skipif(
    not REAL_SOURCE.is_dir(), reason="the Postgres source of the reference is not checked out"
)
def test_reference_files_pass_against_the_real_postgres_source() -> None:
    report = validate_dir(refdata.REFERENCE, source=DirSource(REAL_SOURCE, flat=True))
    assert report.ok, "\n".join(map(str, report.issues))


def test_without_a_source_tree_the_other_rules_still_run() -> None:
    assert validate_dir(refdata.REFERENCE).ok


# ---- one failing fixture per rule -------------------------------------------------------------

Mutation = Callable[[dict[str, Any]], None]


def scene(d: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in d["script.en.json"]["scenes"] if s["id"] == sid)


def m_schema_missing_field(d: dict[str, Any]) -> None:
    del d["script.en.json"]["meta"]["hook"]


def m_schema_extra_field(d: dict[str, Any]) -> None:
    d["script.en.json"]["scenes"][1]["colour"] = "red"


def m_schema_bad_research(d: dict[str, Any]) -> None:
    d["research.json"]["facts"][0]["id"] = "fact-1"


def m_schema_bad_plan(d: dict[str, Any]) -> None:
    d["capture.plan.json"]["ops"][0] = {"op": "teleport"}


def m_ids_duplicate_scene(d: dict[str, Any]) -> None:
    d["script.en.json"]["scenes"][2]["id"] = d["script.en.json"]["scenes"][1]["id"]


def m_ids_duplicate_command(d: dict[str, Any]) -> None:
    scene(d, "s3-folders")["terminal"]["events"][2]["cmd"] = "c-ls-base"


def m_ids_unknown_anchor(d: dict[str, Any]) -> None:
    scene(d, "s3-folders")["panel"]["elements"][0]["appear"] = {"at": "no-such-mark"}


def m_ids_debugger_after_elsewhere(d: dict[str, Any]) -> None:
    scene(d, "s4-create")["debugger"]["after"] = "c-ls-base"


def m_sources_unknown_alias(d: dict[str, Any]) -> None:
    scene(d, "s4-create")["debugger"]["steps"][0]["file"] = "nofile.c"


def m_sources_missing_path(d: dict[str, Any]) -> None:
    d["script.en.json"]["sources"]["utility.c"] = "src/backend/tcop/gone.c"


def m_expect_wrong_text(d: dict[str, Any]) -> None:
    scene(d, "s4-create")["debugger"]["steps"][0]["seq"][1]["expect"] = "SomethingElseEntirely"


def m_expect_outside_ranges(d: dict[str, Any]) -> None:
    scene(d, "s4-create")["debugger"]["steps"][0]["ranges"] = [[766, 767]]


def m_captures_undeclared(d: dict[str, Any]) -> None:
    scene(d, "s2-pg-database")["captions"][0]["lines"][0] = "found {mystery} databases"


def m_captures_unused(d: dict[str, Any]) -> None:
    d["script.en.json"]["captures"]["spare"] = {"description": "never used", "kind": "number"}


def m_numbers_unsourced(d: dict[str, Any]) -> None:
    scene(d, "s2-pg-database")["captions"][0]["lines"][0] = "There are 7 databases"


def m_terms_unexplained(d: dict[str, Any]) -> None:
    for s in d["script.en.json"]["scenes"]:
        for st in (s.get("debugger") or {}).get("steps", []):
            st["notes"] = [n for n in st["notes"] if n["term"] != "Transaction"]
    d["script.en.json"]["scenes"][0]["captions"][0]["lines"][1] = "creates no transaction."


def m_caption_three_lines(d: dict[str, Any]) -> None:
    scene(d, "s2-pg-database")["captions"][0]["lines"] = ["a", "b", "c"]


def m_caption_too_wide(d: dict[str, Any]) -> None:
    scene(d, "s2-pg-database")["captions"][0]["lines"][0] = (
        "This caption line is far too long to fit the area"
    )


def m_note_too_long(d: dict[str, Any]) -> None:
    note = scene(d, "s2-pg-database")["notes"][0]
    note["term"], note["text"] = "t" * 40, "word " * 27 + "word"  # 40 + 2 + 139 characters


def m_duration_too_long(d: dict[str, Any]) -> None:
    scene(d, "s9-outro")["min_duration_s"] = 40


def m_forbidden_next_video(d: dict[str, Any]) -> None:
    scene(d, "s9-outro")["captions"][0]["lines"][1] = "see the *next video*"


def m_forbidden_hash(d: dict[str, Any]) -> None:
    scene(d, "s2-pg-database")["notes"][0]["text"] = "built from e6b2f7c2b41d6261dac1 of the tree"


def m_english_cyrillic(d: dict[str, Any]) -> None:
    scene(d, "s2-pg-database")["captions"][0]["lines"][0] = "Какие базы есть?"


def m_hook_missing(d: dict[str, Any]) -> None:
    del d["script.en.json"]["scenes"][0]["hook"]


def m_hook_late(d: dict[str, Any]) -> None:
    d["script.en.json"]["scenes"][0]["captions"][0]["at"] = {"at_s": 1.0}


def m_cite_bad_quote(d: dict[str, Any]) -> None:
    d["research.json"]["facts"][0]["cite"]["quote"] = "not on that line"


def m_cite_bad_host(d: dict[str, Any]) -> None:
    d["research.json"]["facts"][2]["cite"]["url"] = "https://evil.example.org/page"


def m_call_path_bad_key_line(d: dict[str, Any]) -> None:
    d["research.json"]["call_path"][0]["key_lines"][0]["expect"] = "nothing like this"


def m_plan_missing_run(d: dict[str, Any]) -> None:
    ops = d["capture.plan.json"]["ops"]
    d["capture.plan.json"]["ops"] = [o for o in ops if o.get("cmd") != "c-diff"]


def m_plan_order(d: dict[str, Any]) -> None:
    ops = d["capture.plan.json"]["ops"]
    runs = [i for i, o in enumerate(ops) if o["op"] == "run"]
    ops[runs[0]], ops[runs[1]] = ops[runs[1]], ops[runs[0]]


def m_plan_missing_value(d: dict[str, Any]) -> None:
    ops = d["capture.plan.json"]["ops"]
    d["capture.plan.json"]["ops"] = [o for o in ops if o.get("name") != "n_pages"]


def m_plan_wrong_image(d: dict[str, Any]) -> None:
    d["capture.plan.json"]["image"] = "mysql8"


FIXTURES: list[tuple[str, str, Mutation]] = [
    ("schema", "missing_field", m_schema_missing_field),
    ("schema", "extra_field", m_schema_extra_field),
    ("schema", "research", m_schema_bad_research),
    ("schema", "plan", m_schema_bad_plan),
    ("ids_unique", "duplicate_scene", m_ids_duplicate_scene),
    ("ids_unique", "duplicate_command", m_ids_duplicate_command),
    ("ids_unique", "unknown_anchor", m_ids_unknown_anchor),
    ("ids_unique", "debugger_after", m_ids_debugger_after_elsewhere),
    ("sources_known", "unknown_alias", m_sources_unknown_alias),
    ("sources_known", "missing_path", m_sources_missing_path),
    ("expect_match", "wrong_text", m_expect_wrong_text),
    ("expect_match", "outside_ranges", m_expect_outside_ranges),
    ("captures_declared", "undeclared", m_captures_undeclared),
    ("captures_declared", "unused", m_captures_unused),
    ("numbers_sourced", "unsourced", m_numbers_unsourced),
    ("terms_noted", "unexplained", m_terms_unexplained),
    ("caption_fit", "three_lines", m_caption_three_lines),
    ("caption_fit", "too_wide", m_caption_too_wide),
    ("note_fit", "too_long", m_note_too_long),
    ("duration", "too_long", m_duration_too_long),
    ("no_forbidden", "next_video", m_forbidden_next_video),
    ("no_forbidden", "commit_hash", m_forbidden_hash),
    ("english_only", "cyrillic", m_english_cyrillic),
    ("hook_first", "missing", m_hook_missing),
    ("hook_first", "late", m_hook_late),
    ("cite_valid", "bad_quote", m_cite_bad_quote),
    ("cite_valid", "bad_host", m_cite_bad_host),
    ("call_path_valid", "bad_key_line", m_call_path_bad_key_line),
    ("plan_rules", "missing_run", m_plan_missing_run),
    ("plan_rules", "order", m_plan_order),
    ("plan_rules", "missing_value", m_plan_missing_value),
    ("plan_rules", "wrong_image", m_plan_wrong_image),
]


@pytest.mark.parametrize(("rule", "case", "mutate"), FIXTURES, ids=[f"{r}-{c}" for r, c, _ in FIXTURES])
def test_each_rule_has_a_failing_fixture(rule: str, case: str, mutate: Mutation) -> None:
    docs = refdata.fresh()
    mutate(docs)
    cfg = RuleConfig(research_hosts=("www.postgresql.org", "stackoverflow.com", "github.com"))
    found = run(docs, cfg)
    assert rule in found, f"{rule}/{case} was not reported; got {sorted(found)}"


def test_every_documented_rule_is_covered_by_a_fixture() -> None:
    documented = {
        "ids_unique", "sources_known", "expect_match", "captures_declared", "numbers_sourced", "terms_noted",
        "caption_fit", "note_fit", "duration", "no_forbidden", "english_only", "hook_first", "cite_valid",
        "call_path_valid", "plan_rules", "schema",
    }  # fmt: skip
    assert documented <= {r for r, _, _ in FIXTURES}


def test_duration_fixture_uses_the_settings_limit() -> None:
    docs = refdata.fresh()
    cfg = RuleConfig(duration_min_s=300, duration_max_s=400)
    assert "duration" in run(docs, cfg)


def test_the_unchanged_reference_has_no_issue_under_the_fixture_config() -> None:
    cfg = RuleConfig(research_hosts=("www.postgresql.org", "stackoverflow.com", "github.com"))
    assert run(refdata.fresh(), cfg) == set()


# ---- CLI ---------------------------------------------------------------------------------------


def test_cli_exit_codes_and_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert validate_main([str(refdata.REFERENCE)]) == 0
    assert "OK: 6 files, 0 issues" in capsys.readouterr().out

    broken = tmp_path / "job"
    shutil.copytree(refdata.REFERENCE, broken)
    script = json.loads((broken / "script.en.json").read_text())
    script["scenes"][2]["id"] = script["scenes"][1]["id"]
    (broken / "script.en.json").write_text(json.dumps(script))
    assert validate_main([str(broken), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and any(i["rule"] == "ids_unique" for i in out["issues"])


def test_cli_reports_unreadable_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "script.en.json").write_text("{not json")
    assert validate_main([str(tmp_path)]) == 1
    assert "cannot read JSON" in capsys.readouterr().out
