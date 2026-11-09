"""Starts the agent container for one step and collects what it left (05 section 4).

`DockerLauncher` talks to the Docker SDK at `DOCKER_HOST`; `ReplayLauncher` (MVIDEO_FAKE_AGENT=replay)
produces the same `AgentResult` from recorded files, so the rest of the pipeline cannot tell them apart.
The agent never runs inside the module process: module secrets must not be readable by it.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import structlog

from mvideo.agents.auth import auth_env, scrub
from mvideo.agents.profiles import PROFILES
from mvideo.agents.workspace import Workspace, run_json, tar_of, untar
from mvideo.core_client import Credential
from mvideo.net.egress_proxy import start_listener
from mvideo.pipeline.errors import StepError
from mvideo.settings_model import VideoSettings

log = structlog.get_logger("agent")


@dataclass(slots=True)
class AgentRequest:
    step: str
    step_id: str
    settings: VideoSettings
    workspace: Workspace
    prompt: str
    credential: Credential | None = field(default=None, repr=False)
    resume: str | None = None
    sandbox_mcp: dict[str, Any] | None = None  # {"url": ..., "token": ...} for the capture step
    reading_wps: float | None = None
    max_budget_usd: float | None = None
    settings_values: dict[str, Any] = field(default_factory=dict)
    src_volume: str | None = None


@dataclass(slots=True)
class AgentResult:
    files: dict[str, bytes]  # /out, including _result.json and _transcript.jsonl
    result: dict[str, Any]
    egress_denied: int = 0
    egress_allowed: int = 0
    container_id: str | None = None
    image_digest: str | None = None

    @property
    def names(self) -> set[str]:
        return set(self.files)


class AgentLauncher(Protocol):
    async def run(self, req: AgentRequest) -> AgentResult: ...
    async def cleanup(self, step_id: str) -> None: ...


def step_limits(req: AgentRequest) -> tuple[int, float | None, int]:
    s = req.settings.limits.steps.get(req.step)
    turns = s.max_turns if s else 5
    timeout = s.timeout_s if s else 120
    usd = req.max_budget_usd if req.settings.resolved_cost_mode() == "usd" else None
    return turns, usd, timeout


def allowlist(req: AgentRequest) -> list[str]:
    net = req.settings.network
    prof = PROFILES[req.step]
    extra = net.allow_domains.get(prof.allow_domains_key or "", []) if prof.allow_domains_key else []
    return [*net.anthropic_hosts, *extra]


def container_spec(req: AgentRequest, *, network: str, proxy_url: str) -> dict[str, Any]:
    """Keyword arguments for `containers.create` of the agent. Exactly one auth variable; no docker
    socket, no module environment, no host paths."""
    a = req.settings.agent
    sid = req.step_id
    env = {
        "HTTPS_PROXY": proxy_url, "https_proxy": proxy_url, "NO_PROXY": "module-video",
        "CLAUDE_CONFIG_DIR": "/work/.claude-home", "HOME": "/work",
    }  # fmt: skip
    if req.credential is not None:
        env.update(auth_env(a.auth.mode, req.credential))
    mounts = [
        {"Type": "volume", "Source": f"video-ws-{sid}-work", "Target": "/work", "ReadOnly": False},
        {"Type": "volume", "Source": f"video-ws-{sid}-job", "Target": "/job", "ReadOnly": True},
        {"Type": "volume", "Source": f"video-ws-{sid}-in", "Target": "/in", "ReadOnly": True},
        {"Type": "volume", "Source": f"video-ws-{sid}-ref", "Target": "/ref", "ReadOnly": True},
        {"Type": "volume", "Source": f"video-ws-{sid}-out", "Target": "/out", "ReadOnly": False},
    ]
    if req.src_volume:
        mounts.append({"Type": "volume", "Source": req.src_volume, "Target": "/src", "ReadOnly": True})
    return {
        "image": a.image,
        "command": ["python", "/opt/agent/runner.py", "/job/run.json"],
        "detach": True,
        "working_dir": "/work",
        "environment": env,
        "network": network,
        "read_only": True,
        "tmpfs": {"/tmp": "size=256m"},
        "nano_cpus": int(a.cpus * 1_000_000_000),
        "mem_limit": f"{a.memory_mb}m",
        "memswap_limit": f"{a.memory_mb}m",
        "pids_limit": a.pids,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "mounts": mounts,
        "labels": {"manufacture.module": "video", "manufacture.purpose": "agent", "manufacture.step": sid},
    }


def build_run_json(req: AgentRequest) -> bytes:
    prof = PROFILES[req.step]
    turns, usd, _ = step_limits(req)
    a = req.settings.agent
    mcp: dict[str, Any] = {}
    if prof.capture and req.sandbox_mcp:
        mcp["sandbox"] = {
            "type": "http", "url": req.sandbox_mcp["url"],
            "headers": {"Authorization": f"Bearer {req.sandbox_mcp['token']}"},
        }  # fmt: skip
    model = req.settings.models.get(req.step) or req.settings.model  # type: ignore[call-overload]
    return run_json(
        model=model, max_turns=turns, max_budget_usd=usd, allowed_tools=list(prof.allowed_tools),
        disallowed_tools=a.disallowed_tools, permission_mode=a.permission_mode,
        setting_sources=a.setting_sources, prompt=req.prompt, resume=req.resume, mcp_servers=mcp,
        settings=req.settings_values, reading_wps=req.reading_wps,
    )  # fmt: skip


class DockerLauncher:
    def __init__(self, client: Any, *, network: str | None = None, proxy_host: str = "module-video") -> None:
        self.client = client
        self.network = network or os.environ.get("VIDEO_AGENT_NETWORK", "video-agents")
        self.proxy_host = proxy_host

    # blocking Docker calls run in threads
    def _populate(self, req: AgentRequest, spec: dict[str, Any]) -> None:
        sid = req.step_id
        names = ("work", "job", "in", "ref", "out")
        for n in names:
            self.client.volumes.create(name=f"video-ws-{sid}-{n}", labels={"manufacture.step": sid})
        mounts = [{**m, "ReadOnly": False} for m in spec["mounts"] if m["Target"] != "/src"]
        helper = self.client.containers.create(
            image=spec["image"], command=["true"], mounts=mounts, network_mode="none", user="root",
            labels={"manufacture.module": "video", "manufacture.purpose": "populate"},
        )  # fmt: skip
        try:
            helper.put_archive("/work", tar_of(req.workspace.work))
            helper.put_archive("/job", tar_of({"run.json": build_run_json(req)}))
            helper.put_archive("/in", tar_of(req.workspace.inputs))
            helper.put_archive("/ref", tar_of(req.workspace.ref))
        finally:
            helper.remove(force=True)

    def _collect(self, container: Any) -> dict[str, bytes]:
        stream, _ = container.get_archive("/out")
        return untar(b"".join(stream))

    def _run_blocking(
        self, req: AgentRequest, spec: dict[str, Any], timeout_s: int
    ) -> tuple[AgentResult, bool]:
        self._populate(req, spec)
        container = self.client.containers.create(**spec)
        timed_out = False
        try:
            container.start()
            try:
                container.wait(timeout=timeout_s)
            except Exception:
                timed_out = True
                container.kill()
            files = self._collect(container)
            logs = container.logs(tail=200).decode("utf-8", "replace")
            secret = [req.credential.value] if req.credential else []
            log.info("agent_exit", step=req.step, tail=scrub(logs, secret)[-500:])
            result = json.loads(files["_result.json"]) if "_result.json" in files else {
                "is_error": True, "subtype": "no_result", "errors": [scrub(logs, secret)[-500:]],
            }  # fmt: skip
            image = self.client.images.get(spec["image"])
            return AgentResult(files, result, container_id=container.id, image_digest=image.id), timed_out
        finally:
            container.remove(force=True)

    async def run(self, req: AgentRequest) -> AgentResult:
        _, _, timeout_s = step_limits(req)
        lo, hi = req.settings.network.proxy_ports
        listener = await start_listener(allowlist(req), (lo, hi))
        spec = container_spec(
            req, network=self.network, proxy_url=f"http://{self.proxy_host}:{listener.port}"
        )
        t0 = time.monotonic()
        try:
            res, timed_out = await asyncio.to_thread(self._run_blocking, req, spec, timeout_s)
        finally:
            await listener.close()
        res.egress_denied, res.egress_allowed = listener.stats.denied, listener.stats.allowed
        if timed_out:
            raise StepError(
                "fatal", "step_timeout", f"agent step {req.step} exceeded {timeout_s} s", step=req.step,
                details={"elapsed_s": round(time.monotonic() - t0)},
            )  # fmt: skip
        return res

    async def cleanup(self, step_id: str) -> None:
        def _rm() -> None:
            for v in self.client.volumes.list(filters={"label": f"manufacture.step={step_id}"}):
                v.remove(force=True)

        await asyncio.to_thread(_rm)


# ---- replay -----------------------------------------------------------------------------------------

SCENARIOS: dict[str, dict[str, Any]] = {
    "ok": {"is_error": False, "subtype": "success", "num_turns": 3, "total_cost_usd": 0.12,
           "usage": {"input_tokens": 12000, "output_tokens": 3000}, "stop_reason": "end_turn"},
    "rate_limit": {"is_error": True, "subtype": "success", "api_error_status": 429, "num_turns": 1,
                   "result_text": "Claude usage limit reached",
                   "rate_limit": {"status": "rejected", "resets_at": None}},
    "auth_failed": {"is_error": True, "subtype": "success", "api_error_status": 401, "num_turns": 0,
                    "result_text": "Invalid API key - please run /login"},
    "max_turns": {"is_error": True, "subtype": "error_max_turns", "num_turns": 20,
                  "terminal_reason": "max_turns"},
    "budget": {"is_error": True, "subtype": "error_max_budget_usd", "num_turns": 7},
}  # fmt: skip


class ReplayLauncher:
    """`MVIDEO_FAKE_AGENT=replay`: files from `<root>/<step>/files/`, scenario from `<root>/<step>/scenario`
    (a name in SCENARIOS) or the `scenario` argument. Nothing is started; no network is used."""

    def __init__(self, root: str | Path, scenario: str | None = None) -> None:
        self.root = Path(root)
        self.scenario = scenario
        self.calls: list[AgentRequest] = []

    async def run(self, req: AgentRequest) -> AgentResult:
        self.calls.append(req)
        step_dir = self.root / req.step
        n = len([c for c in self.calls if c.step == req.step])
        name = self.scenario or os.environ.get("MVIDEO_REPLAY_SCENARIO")
        marker = step_dir / "scenario"
        if not name:
            name = marker.read_text().strip() if marker.is_file() else "ok"
        result = {
            "sdk_version": "replay",
            "cli_version": "replay",
            "session_id": f"replay-{req.step}",
            **SCENARIOS[name],
        }
        files: dict[str, bytes] = {}
        if name == "ok":
            # call 1 reads files/, call 2 reads files.2/ (a resume), and so on; the last one repeats
            dirs = [step_dir / "files"] + [step_dir / f"files.{i}" for i in range(2, n + 1)]
            chosen = next((d for d in reversed(dirs) if d.is_dir()), None)
            for f in sorted(chosen.glob("*")) if chosen else []:
                files[f.name] = f.read_bytes()
        files["_result.json"] = json.dumps(result).encode()
        files["_transcript.jsonl"] = b""
        return AgentResult(files, result)

    async def cleanup(self, step_id: str) -> None:
        return None


def launcher_from_env(client: Any = None) -> AgentLauncher:
    """`MVIDEO_FAKE_AGENT=replay` (with `MVIDEO_REPLAY_DIR`) selects the replay agent."""
    if os.environ.get("MVIDEO_FAKE_AGENT") == "replay":
        return ReplayLauncher(os.environ.get("MVIDEO_REPLAY_DIR", "replay"))
    if client is None:
        from mvideo.sandbox.executor import make_client

        client = make_client()
    return DockerLauncher(client)
