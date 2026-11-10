from __future__ import annotations

from pathlib import Path

from mscenario.sources import SourceTree, allowed_pin_source
from mscenario.verify import check_cite, check_document, check_facts, domain_allowed, schema_issues


def make_tree(tmp_path: Path) -> SourceTree:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.c").write_text("one\n  two   words\nthree\n")
    return SourceTree(tmp_path)


def test_code_citation_checks_file_line_and_quote(tmp_path: Path) -> None:
    t = make_tree(tmp_path)
    ok = {"file": "a/x.c", "line": 2, "quote": "two words"}  # whitespace is normalised
    assert check_cite(ok, "/c", t, []) == []
    assert "does not exist" in check_cite({**ok, "line": 9}, "/c", t, [])[0].message
    assert "not found on" in check_cite({**ok, "quote": "nope"}, "/c", t, [])[0].message
    assert check_cite({**ok, "file": "a/missing.c"}, "/c", t, [])
    assert check_cite({**ok, "file": "../etc/passwd"}, "/c", t, [])
    assert check_cite({**ok, "file": "/etc/passwd"}, "/c", t, [])
    assert check_cite(ok, "/c", None, [])[0].message.startswith("a code citation needs")


def test_url_citation_domain_allowlist() -> None:
    assert domain_allowed("https://docs.github.com/x", ["github.com"])
    assert not domain_allowed("https://evilgithub.com/x", ["github.com"])
    assert not domain_allowed("http://github.com/x", ["github.com"])
    cite = {"url": "https://example.org/p", "quote": "something"}
    assert "not an allowed" in check_cite(cite, "/c", None, ["github.com"])[0].message
    ok = {"url": "https://github.com/p", "quote": "something"}
    assert check_cite(ok, "/c", None, ["github.com"], lambda u, q: True) == []
    assert check_cite(ok, "/c", None, ["github.com"], lambda u, q: False)


def test_measurement_from_a_web_page_is_not_a_fact(tmp_path: Path) -> None:
    fact = {"text": "creating it takes 50 ms", "cite": {"url": "https://github.com/p", "quote": "fast enough"}}
    issues = check_facts([fact], None, ["github.com"])
    assert any("capture_needs" in i.message for i in issues)
    documented = {"text": "a page is 8192 bytes (8 KB)", "cite": {"url": "https://github.com/p", "quote": "8 kB"}}
    assert check_facts([documented], None, ["github.com"]) == []  # a constant the page really states
    code = {"text": "BLCKSZ is 8192 bytes", "cite": {"file": "a/x.c", "line": 1, "quote": "one"}}
    assert check_facts([code], make_tree(tmp_path), []) == []  # a constant read from the source is a fact


def test_allowed_pin_source() -> None:
    allowed = ["https://github.com/postgres/postgres.git", {"repo": "https://github.com/x/y", "refs": ["v1"]}]
    assert allowed_pin_source("https://github.com/postgres/postgres", "REL_17", allowed)
    assert allowed_pin_source("https://github.com/x/y", "v1", allowed)
    assert not allowed_pin_source("https://github.com/x/y", "v2", allowed)
    assert not allowed_pin_source("https://github.com/other/repo", "main", allowed)


def doc(**kw: object) -> dict:  # type: ignore[type-arg]
    base = {
        "facts": [{"id": "f1", "text": "t", "cite": {}, "origin": "new"}],
        "misconceptions": [], "capture_needs": [], "terms": [], "call_path": [],
    }  # fmt: skip
    return {**base, **kw}


def test_document_cross_references(tmp_path: Path) -> None:
    t = make_tree(tmp_path)
    assert check_document(doc(), t) == []
    bad = doc(misconceptions=[{"claim": "c", "truth": "t", "facts": ["f9"]}])
    assert "unknown fact" in check_document(bad, t)[0].message
    dup = doc(capture_needs=[{"name": "n"}, {"name": "n"}], terms=[{"term": "A"}, {"term": "a"}])
    assert len(check_document(dup, t)) == 2
    path = doc(call_path=[{"function": "f", "file": "a/x.c", "line_start": 1, "line_end": 3, "role": "r",
                           "key_lines": [{"n": 2, "expect": "nothing", "why": "w"}]}])  # fmt: skip
    assert "does not contain" in check_document(path, t)[0].message


def test_delta_schema_rejects_unknown_fields_and_bad_ids() -> None:
    assert (
        schema_issues(
            "delta", {"format": "manufacture.research.delta/1", "feasibility": {"decision": "go", "reason": "r"}}
        )
        == []
    )
    bad = {"format": "manufacture.research.delta/1", "feasibility": {"decision": "go", "reason": "r"}, "x": 1,
           "facts": [{"id": "7", "text": "t", "cite": {"file": "a", "line": 1, "quote": "abcd"}}]}  # fmt: skip
    assert len(schema_issues("delta", bad)) >= 2
