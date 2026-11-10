"""B7: outcomes, auth variables, container spec, replay agent, source cache planning."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from mvideo.agents import auth, launcher, outcomes
from mvideo.agents.profiles import NEVER, PROFILES
from mvideo.agents.run import compute_cost, run_agent
from mvideo.agents.workspace import Workspace, tar_of, untar
from mvideo.core_client import Credential
from mvideo.pipeline.errors import StepError
from mvideo.settings_model import VideoSettings
from mvideo.sources import git_cache
from tests.helpers import settings_values

NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


def settings(**agent_auth: str) -> VideoSettings:
    v = settings_values()
    if agent_auth:
        v["agent"] = {**v["agent"], "auth": agent_auth}
    return VideoSettings.model_validate(v)


def request(
    step: str = "script", s: VideoSettings | None = None, token: str | None = "sk-secret-1"
) -> launcher.AgentRequest:
    s = s or settings()
    cred = Credential("cred:x", "claude_oauth_token", token) if token else None
    ws = Workspace.build(claude_md="# rules", task_md="do it", inputs={"research.json": b"{}"})
    return launcher.AgentRequest(step, "step1", s, ws, "do it", credential=cred)


# ---- auth ------------------------------------------------------------------------------------------


def test_one_auth_variable_per_mode() -> None:
    c = Credential("cred:x", "k", "TOKEN")
    assert auth.auth_env("subscription", c) == {"CLAUDE_CODE_OAUTH_TOKEN": "TOKEN"}
    assert auth.auth_env("api_key", c) == {"ANTHROPIC_API_KEY": "TOKEN"}
    for mode in ("subscription", "api_key"):
        assert len(set(auth.auth_env(mode, c)) & auth.ALL_AUTH_VARS) == 1  # type: ignore[arg-type]


def test_container_env_has_one_auth_var_and_no_module_secrets() -> None:
    for mode, var in (("subscription", "CLAUDE_CODE_OAUTH_TOKEN"), ("api_key", "ANTHROPIC_API_KEY")):
        s = settings(mode=mode)
        spec = launcher.container_spec(
            request(s=s), network="video-agents", proxy_url="http://module-video:3200"
        )
        env = spec["environment"]
        assert set(env) & auth.ALL_AUTH_VARS == {var}
        assert not any(k.startswith(("MODULE_", "VIDEO_", "S3_", "DOCKER")) for k in env)
        assert env["HTTPS_PROXY"] == "http://module-video:3200"


def test_container_spec_is_closed() -> None:
    spec = launcher.container_spec(request(), network="video-agents", proxy_url="http://p:1")
    assert spec["cap_drop"] == ["ALL"] and spec["read_only"] is True
    assert spec["security_opt"] == ["no-new-privileges"]
    assert spec["network"] == "video-agents" and not spec.get("privileged")
    targets = {m["Target"]: m for m in spec["mounts"]}
    assert set(targets) == {"/work", "/job", "/in", "/ref", "/out"}
    assert all(m["Type"] == "volume" for m in spec["mounts"])  # no host paths, no docker socket
    assert targets["/in"]["ReadOnly"] is True and targets["/job"]["ReadOnly"] is True
    assert spec["pids_limit"] == 256 and spec["mem_limit"] == "2048m"


def test_scrub_removes_secret() -> None:
    assert auth.scrub("token sk-secret-1 here", ["sk-secret-1"]) == "token [REDACTED] here"


def test_run_json_has_no_credentials_and_follows_settings() -> None:
    body = json.loads(launcher.build_run_json(request("script")))
    assert "sk-secret-1" not in json.dumps(body)
    assert body["permission_mode"] == "dontAsk" and body["setting_sources"] == ["project"]
    assert body["max_turns"] == 40 and body["model"] == "claude-opus-5-5"
    assert set(NEVER) <= set(body["disallowed_tools"]) and not set(NEVER) & set(body["allowed_tools"])
    assert body["max_budget_usd"] is None  # subscription: estimate mode, no budget stop
    api = json.loads(launcher.build_run_json(request("script", settings(mode="api_key"))))
    assert api["max_budget_usd"] is None  # no remaining budget was supplied


def test_profiles_never_allow_bash() -> None:
    for p in PROFILES.values():
        assert not set(NEVER) & set(p.allowed_tools)
    assert "mcp__sandbox__sandbox_try" in PROFILES["capture"].allowed_tools


def test_allowlist_per_step() -> None:
    assert launcher.allowlist(request("script")) == ["api.anthropic.com"]
    assert "github.com" in launcher.allowlist(request("research"))


# ---- outcomes --------------------------------------------------------------------------------------


def test_outcome_mapping() -> None:
    ok = outcomes.classify({}, {"script.en.json", "_result.json"})
    assert ok.kind == "outputs"
    assert outcomes.classify({}, {"blocked.json"}).kind == "blocked"
    rl = outcomes.classify(
        {"is_error": True, "api_error_status": 429}, {"_result.json"}, backoff_s=900, now=NOW
    )
    assert (rl.kind, rl.details["retry_after"]) == ("rate_limited", 900)
    reset = int(NOW.timestamp()) + 5400
    rl2 = outcomes.classify(
        {"is_error": True, "rate_limit": {"status": "rejected", "resets_at": reset}}, set(), now=NOW
    )
    assert rl2.details["retry_after"] == 5400 and rl2.details["reported"] is True
    assert outcomes.classify({"is_error": True, "api_error_status": 401}, set()).kind == "auth_failed"
    assert (
        outcomes.classify({"is_error": True, "result_text": "OAuth token has expired"}, set()).kind
        == "auth_failed"
    )
    assert outcomes.classify({"subtype": "error_max_turns"}, set()).kind == "turns_exceeded"
    assert (
        outcomes.classify({"subtype": "error_max_budget_usd"}, set(), cost_mode="usd").kind
        == "budget_exceeded"
    )
    assert (
        outcomes.classify({"subtype": "error_max_budget_usd"}, set(), cost_mode="estimate").kind == "failed"
    )
    err = outcomes.to_error(outcomes.Outcome("auth_failed"), "script")
    assert err and (err.error_class, err.code) == ("blocked", "agent_auth_failed")
    err = outcomes.to_error(outcomes.Outcome("rate_limited", details={"retry_after": 60}), "script")
    assert err and (err.error_class, err.code, err.details["retry_after"]) == (
        "transient",
        "agent_rate_limited",
        60,
    )


def test_cost_modes() -> None:
    res = {"total_cost_usd": 0.5, "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}
    assert compute_cost(res, "usd").usd == 0.5 and not compute_cost(res, "usd").estimated
    est = compute_cost(res, "estimate")
    assert est.estimated and est.usd > 0 and est.tokens_in == 1_000_000


# ---- replay agent ----------------------------------------------------------------------------------


@pytest.fixture
def replay_dir(tmp_path: Path) -> Path:
    (tmp_path / "script" / "files").mkdir(parents=True)
    (tmp_path / "script" / "files" / "script.en.json").write_text('{"x": 1}')
    return tmp_path


async def test_replay_ok_returns_files_and_cost(replay_dir: Path) -> None:
    res, outcome, cost = await run_agent(launcher.ReplayLauncher(replay_dir), request("script"))
    assert outcome.kind == "outputs" and res.files["script.en.json"] == b'{"x": 1}'
    assert cost.estimated and cost.tokens_in == 12000  # subscription: estimated from usage


@pytest.mark.parametrize("both_modes", ["subscription", "api_key"])
async def test_replay_rate_limit_and_auth_failed_in_both_modes(replay_dir: Path, both_modes: str) -> None:
    s = settings(mode=both_modes)
    with pytest.raises(StepError) as e:
        await run_agent(launcher.ReplayLauncher(replay_dir, "rate_limit"), request("script", s))
    assert (e.value.error_class, e.value.code, e.value.details["retry_after"]) == (
        "transient", "agent_rate_limited", s.limits.rate_limit_backoff_s,
    )  # fmt: skip
    with pytest.raises(StepError) as e2:
        await run_agent(launcher.ReplayLauncher(replay_dir, "auth_failed"), request("script", s))
    assert (e2.value.error_class, e2.value.code) == ("blocked", "agent_auth_failed")


def test_launcher_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MVIDEO_FAKE_AGENT", "replay")
    monkeypatch.setenv("MVIDEO_REPLAY_DIR", str(tmp_path))
    assert isinstance(launcher.launcher_from_env(), launcher.ReplayLauncher)


def test_tar_roundtrip() -> None:
    assert set(untar(tar_of({"out/x.json": b"1"}))) == {"x.json"}


# ---- source cache ----------------------------------------------------------------------------------

URL = "https://github.com/postgres/postgres"
SHA = "e6b2f7c2b41d6261dac15825dede55e94ca35614"


def test_volume_name_and_commands() -> None:
    name = git_cache.volume_name(URL, SHA)
    assert (
        name.startswith("video-src-")
        and name.endswith("-e6b2f7c2b41d")
        and len(name) == len("video-src-") + 12 + 13
    )
    cmds = git_cache.git_commands(URL, SHA)
    assert cmds[0][:3] == ["clone", "--filter=blob:none", "--no-checkout"]
    assert cmds[1] == ["fetch", "--depth", "1", "origin", SHA]
    with pytest.raises(ValueError):
        git_cache.git_commands(URL, "REL_17_STABLE")  # a branch name is not a pin


def test_repo_must_be_allowed() -> None:
    s = settings()
    git_cache.check_allowed(URL, s.sources.allowed_repos)
    with pytest.raises(StepError):
        git_cache.check_allowed("https://evil.example/x", s.sources.allowed_repos)


def test_eviction_is_lru_and_keeps_in_use() -> None:
    e = [git_cache.CacheEntry("u", c, f"v{c}", 10, t) for c, t in (("a", 1), ("b", 2), ("c", 3), ("d", 4))]
    assert [x.commit for x in git_cache.plan_eviction(e, 25)] == ["a", "b"]
    assert [x.commit for x in git_cache.plan_eviction(e, 25, keep={"va"})] == ["b", "c"]
    assert git_cache.plan_eviction(e, 100) == []


# ---- runner tools (run inside the agent container; no SDK needed) ----------------------------------


def test_runtime_validate_and_estimate_and_source_line(tmp_path: Path) -> None:
    import shutil

    from mvideo.agents import runtime
    from tests import refdata

    ref = refdata.REFERENCE
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    in_dir.mkdir()
    out_dir.mkdir()
    for f in ("research.json", "analysis.json"):
        shutil.copy(ref / f, in_dir / f)
    shutil.copy(ref / "script.en.json", out_dir / "script.en.json")
    res = runtime.validate_tool(in_dir, out_dir, ref / "sources", None)
    assert res["checked"] == ["script.en.json"] and res["unreadable"] == []
    assert isinstance(res["issues"], list)
    # a broken script is reported, with the file name, on the same tool
    (out_dir / "script.en.json").write_text('{"format": "nope"}')
    bad = runtime.validate_tool(in_dir, out_dir, None, None)
    assert bad["ok"] is False and bad["issues"]
    shutil.copy(ref / "script.en.json", out_dir / "script.en.json")
    est = runtime.estimate_tool(out_dir, in_dir, None, 2.6)
    assert est["total_s"] > 60 and est["scenes"]
    line = runtime.source_line_tool(ref / "sources", "src/backend/commands/dbcommands.c", 1458)
    assert line["exists"] and "CatalogTupleInsert" in (line["text"] or "")
