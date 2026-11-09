"""B6: container templates (always run) and the capture executor (needs Docker).

The Docker tests are marked `docker`. They need a reachable Docker daemon (DOCKER_HOST, or the
current `docker context`) and the image `postgres:17` present locally; they skip otherwise.
Run them alone with `uv run pytest -m docker`.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import pytest

from mvideo.sandbox import executor, templates
from mvideo.settings_model import DEFAULT_PALETTE, VideoSettings
from tests import refdata
from tests.helpers import DIGEST, settings_values

PG_IMAGE_KEY = "postgres17"


def pg_settings(image_ref: str) -> VideoSettings:
    values = settings_values()
    values["sandbox_images"] = {
        PG_IMAGE_KEY: {
            "image": image_ref,
            "env": {"POSTGRES_HOST_AUTH_METHOD": "trust"},
            "exec_user": "postgres",
            "tmpfs": {
                "/var/lib/postgresql/data": "size=1g",
                "/var/run/postgresql": "size=16m",
                "/tmp": "size=256m",
            },
            "cap_add": ["CHOWN", "SETUID", "SETGID", "FOWNER", "DAC_OVERRIDE"],
            # TCP only: the temporary server of the entrypoint listens on the socket alone
            "ready_cmd": "pg_isready -h 127.0.0.1 -U postgres",
            "version_cmd": "psql -U postgres -tAc 'SELECT version()'",
            "version_expect": "PostgreSQL 17.",
            "sessions": {
                "psql": {"kind": "psql", "start": "psql -U postgres -d {database}"},
                "sh": {"kind": "sh", "start": "bash --noprofile --norc"},
            },
        }
    }
    values["palette"] = DEFAULT_PALETTE
    return VideoSettings.model_validate(values)


def test_template_has_no_binds_privileges_or_host_network() -> None:
    s = pg_settings(f"postgres:17@{DIGEST}")
    spec = templates.container_spec(s.sandbox_images[PG_IMAGE_KEY], s.sandbox, run_id="r1")
    for key in templates.FORBIDDEN_KEYS:
        assert key not in spec
    assert spec["network_mode"] == "none"
    assert spec["read_only"] is True
    assert spec["cap_drop"] == ["ALL"]
    assert spec["security_opt"] == ["no-new-privileges"]
    assert spec["mem_limit"] == spec["memswap_limit"] == "2048m"
    assert spec["pids_limit"] == 512 and spec["nano_cpus"] == 2_000_000_000
    assert spec["labels"]["manufacture.run"] == "r1"
    assert "volumes" not in spec and not spec.get("privileged")


def test_template_requires_a_digest() -> None:
    s = pg_settings(f"postgres:17@{DIGEST}")
    unpinned = s.sandbox_images[PG_IMAGE_KEY].model_copy(update={"image": "postgres:17"})  # no validation
    with pytest.raises(templates.TemplateError):
        templates.container_spec(unpinned, s.sandbox)


def test_parse_modes() -> None:
    assert executor._parse(["16384"], "single") == "16384"
    assert executor._parse(["1", "2"], "single") == ""
    assert executor._parse(["a", "b"], "first_line") == "a"
    assert executor._parse(["a", "", "b"], "count_lines") == "2"


def _norm(lines: list[str]) -> list[str]:
    out = [x.rstrip() for x in lines]
    while out and out[-1] == "":
        out.pop()
    return out


# ---- Docker -------------------------------------------------------------------------------------


def _docker_host() -> str | None:
    if os.environ.get("DOCKER_HOST"):
        return os.environ["DOCKER_HOST"]
    try:
        out = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


@pytest.fixture(scope="module")
def docker_client() -> Any:
    try:
        client = executor.make_client(_docker_host())
        client.ping()
        return client
    except Exception as exc:
        pytest.skip(f"no Docker daemon: {exc}")


@pytest.fixture(scope="module")
def pg_ref(docker_client: Any) -> str:
    try:
        image = docker_client.images.get("postgres:17")
    except Exception:
        pytest.skip("image postgres:17 is not present locally (docker pull postgres:17)")
    digests = image.attrs.get("RepoDigests") or []
    if not digests:
        pytest.skip("postgres:17 has no repo digest")
    return str(digests[0])


@pytest.mark.docker
def test_reference_plan_reproduces_reference_values(docker_client: Any, pg_ref: str) -> None:
    s = pg_settings(pg_ref)
    plan = refdata.load("capture.plan.json")
    script = refdata.load("script.en.json")
    expected = refdata.load("capture.json")
    capture, log = executor.run_capture(docker_client, s, plan, script, run_id="test-b6")

    got = {k: v["value"] for k, v in capture["values"].items()}
    want = {k: v["value"] for k, v in expected["values"].items()}
    # 16384 / 16466 / 222 / 14 / 298 on the reference image; the OIDs follow from a fresh cluster
    assert got == want, log
    assert executor.check_values(capture) == []
    assert capture["version"]["pass"] and capture["image"]["digest"].startswith("sha256:")
    assert capture["limits"] == expected["limits"]

    # statuses, prompts and transaction state follow the reference
    for cid, rec in expected["commands"].items():
        mine = capture["commands"][cid]
        assert mine["status"] == rec["status"], cid
        assert mine["prompt_after"] == rec["prompt_after"], cid
        # psql pads table headers and ends tables with a blank line; the reference file is not exact there
        assert _norm(mine["output"]) == _norm(rec["output"]), (cid, mine["output"])
        assert mine.get("tx_state") == rec.get("tx_state"), cid
        assert mine["seq"] == rec["seq"], cid
    assert capture["commands"]["c-create-x"]["status"] == "error"
    assert capture["commands"]["c-create-x"]["tx_state"] == "failed"
    assert capture["hidden"] == expected["hidden"]
    json.dumps(capture)


@pytest.mark.docker
def test_containers_are_removed_after_the_run(docker_client: Any, pg_ref: str) -> None:
    s = pg_settings(pg_ref)
    plan = {
        "format": "manufacture.capture-plan/1", "image": PG_IMAGE_KEY,
        "sessions": {"psql": {"kind": "psql", "database": "postgres", "open_at_start": True}},
        "ops": [{"op": "value", "name": "one", "session": "psql", "query": "SELECT 1", "why_equal": "x"}],
    }  # fmt: skip
    script = {"scenes": [], "captures": {"one": {"kind": "number"}}}
    capture, _ = executor.run_capture(docker_client, s, plan, script, run_id="test-b6-clean")
    assert capture["values"]["one"]["value"] == "1"
    left = docker_client.containers.list(all=True, filters={"label": "manufacture.run=test-b6-clean"})
    assert left == []


@pytest.mark.docker
def test_sandbox_has_no_network(docker_client: Any, pg_ref: str) -> None:
    s = pg_settings(pg_ref)
    image = s.sandbox_images[PG_IMAGE_KEY]
    with executor.sandbox_container(docker_client, image, s, purpose="capture", run_id="test-b6-net") as c:
        executor.wait_ready(c, image, 60)
        info = docker_client.api.inspect_container(c.id)
        assert info["HostConfig"]["NetworkMode"] == "none"
        assert info["HostConfig"]["Privileged"] is False
        assert not info["HostConfig"].get("Binds")
        assert all(m["Type"] == "tmpfs" for m in info["Mounts"])
