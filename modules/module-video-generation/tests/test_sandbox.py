from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from mvgen.sandbox.config import SandboxCatalog, SandboxImage
from mvgen.sandbox.executor import _parse, _value_query, plan_sha256, script_commands
from mvgen.sandbox.templates import TemplateError, container_spec, digest_of, limits_record, require_digest

DIGEST = "sha256:" + "a" * 64
CATALOG: dict[str, Any] = {
    "images": {
        "postgres17": {
            "image": f"postgres@{DIGEST}", "description": "PostgreSQL 17", "ready_cmd": "pg_isready",
            "version_cmd": "postgres --version", "version_expect": "17", "tmpfs": {"/tmp": ""},
            "sessions": {"psql": {"kind": "psql"}, "sh": {"kind": "sh", "start": "sh"}},
        }
    },
    "limits": {"cpus": 1.5, "memory_mb": 1024},
}  # fmt: skip


def test_container_spec_enforces_the_isolation_rules() -> None:
    cat = SandboxCatalog.model_validate(CATALOG)
    spec = container_spec(cat.images["postgres17"], cat.limits, purpose="capture", run_id="r1")
    assert spec["network_mode"] == "none" and spec["read_only"] and spec["cap_drop"] == ["ALL"]
    assert spec["security_opt"] == ["no-new-privileges"] and spec["mem_limit"] == spec["memswap_limit"] == "1024m"
    assert spec["nano_cpus"] == 1_500_000_000 and spec["labels"]["manufacture.run"] == "r1"
    assert not {"volumes", "binds", "privileged", "devices"} & set(spec)


def test_images_must_be_pinned_by_digest() -> None:
    bad = {**CATALOG["images"]["postgres17"], "image": "postgres:17"}
    with pytest.raises(ValueError):
        SandboxImage.model_validate(bad)
    with pytest.raises(TemplateError):
        require_digest("postgres:17")
    assert digest_of(f"postgres@{DIGEST}") == DIGEST


def test_limits_record_and_describe() -> None:
    cat = SandboxCatalog.model_validate(CATALOG)
    assert limits_record(cat.limits) == {"cpus": 1.5, "memory_mb": 1024, "pids": 512, "network": "none"}
    d = cat.describe("postgres17")
    assert d["version_expect"] == "17" and d["sessions"]["sh"]["start"] == "sh"


def test_catalog_loads_from_json(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps(CATALOG))
    assert "postgres17" in SandboxCatalog.load(p).images


def test_parse_and_value_query_and_commands() -> None:
    assert _parse([" 5 ", ""], "single") == "5" and _parse(["a", "b"], "single") == ""
    assert _parse(["a", "b"], "first_line") == "a" and _parse(["x", "y", ""], "count_lines") == "2"
    assert "tuples_only=on" in _value_query("psql", "select 1;") and _value_query("sh", "ls") == "ls"
    script = {"scenes": [{"terminal": {"session": "sh", "events": [{"cmd": "c1", "text": "ls"}, {"type": "x"}]}}]}
    assert script_commands(script) == {"c1": {"text": "ls", "session": "sh"}}
    assert plan_sha256({"a": 1, "b": 2}) == plan_sha256({"b": 2, "a": 1})


@pytest.mark.docker
async def test_real_capture_in_a_sandbox() -> None:
    """Needs a daemon and MVGEN_DOCKER_IMAGE=<postgres ref pinned by digest>; skipped otherwise."""
    ref = os.environ.get("MVGEN_DOCKER_IMAGE")
    if not ref:
        pytest.skip("MVGEN_DOCKER_IMAGE is not set")
    from mvgen.sandbox.runner import DockerCaptureRunner

    raw = json.loads((Path(__file__).resolve().parents[1] / "sandbox-catalog.example.json").read_text())
    raw["images"]["postgres17"]["image"] = ref
    cat = SandboxCatalog.model_validate(raw)
    plan = {"image": "postgres17", "sessions": {"psql": {"kind": "psql", "database": "postgres", "open_at_start": True}},
            "ops": [{"op": "run", "cmd": "c1"}, {"op": "value", "name": "n", "session": "psql", "query": "select 41+1", "parse": "single", "why_equal": "x"}]}  # fmt: skip
    script = {
        "scenes": [{"terminal": {"session": "psql", "events": [{"cmd": "c1", "text": "select 1;"}]}}],
        "captures": {"n": {"kind": "number"}},
    }
    capture, log = await DockerCaptureRunner(cat).run(plan, script, "t1")
    assert capture["values"]["n"]["value"] == "42" and "run c1" in log
