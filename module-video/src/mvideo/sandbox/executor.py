"""Runs a capture plan in a fresh sandbox and writes `capture.json` (05 section 2.5, 04 section 6)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import docker

from mvideo.sandbox.sessions import (
    CommandResult,
    PsqlSession,
    SessionError,
    ShSession,
)  # fmt: skip
from mvideo.sandbox.templates import container_spec, digest_of, limits_record
from mvideo.settings_model import SandboxImage, VideoSettings

NUMBER = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


class CaptureFailure(Exception):
    """The capture could not be produced; `code` is `version_mismatch`, `not_reproducible` or `timeout`."""

    def __init__(self, code: str, message: str, log: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.log = log


def make_client(host: str | None = None) -> docker.DockerClient:
    """Docker SDK client for `DOCKER_HOST` (the socket proxy in deployment)."""
    base = host or os.environ.get("DOCKER_HOST")
    return docker.DockerClient(base_url=base) if base else docker.from_env()


def plan_sha256(plan: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def script_commands(script: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Script command id -> {text, session}, in scene order."""
    out: dict[str, dict[str, str]] = {}
    for scene in script.get("scenes", []):
        term = scene.get("terminal") or {}
        for ev in term.get("events", []):
            if "cmd" in ev:
                out[ev["cmd"]] = {"text": ev["text"], "session": ev.get("session") or term.get("session", "")}
    return out


@contextmanager
def sandbox_container(
    client: docker.DockerClient, image: SandboxImage, settings: VideoSettings, *, purpose: str, run_id: str
) -> Iterator[Any]:
    """A started sandbox container that is ready and is removed on exit, whatever happens."""
    ref = image.image
    spec = container_spec(image, settings.sandbox, purpose=purpose, run_id=run_id)
    try:
        client.images.get(ref)
    except docker.errors.ImageNotFound:
        client.images.pull(ref)
    container = client.containers.create(**spec)
    try:
        container.start()
        yield container
    finally:
        with suppress(docker.errors.NotFound):
            container.remove(force=True, v=True)


def wait_ready(container: Any, image: SandboxImage, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        code, _ = container.exec_run(["sh", "-c", image.ready_cmd])
        if code == 0:
            return
        if time.monotonic() > deadline:
            raise CaptureFailure("timeout", f"sandbox not ready after {timeout_s:.0f} s")
        time.sleep(0.5)


def check_version(container: Any, image: SandboxImage) -> dict[str, Any]:
    _, out = container.exec_run(["sh", "-c", image.version_cmd])
    text = out.decode("utf-8", "replace").strip()
    return {"cmd": image.version_cmd, "output": text, "expect": image.version_expect,
            "pass": image.version_expect in text}  # fmt: skip


def _parse(raw: list[str], mode: str) -> str:
    lines = [ln.strip() for ln in raw if ln.strip()]
    if mode == "count_lines":
        return str(len(lines))
    if not lines:
        return ""
    if mode == "first_line":
        return lines[0]
    return lines[0] if len(lines) == 1 else ""  # single: exactly one line, else empty (a check fails)


def _value_query(kind: str, query: str) -> str:
    if kind == "psql":
        return query.strip().rstrip(";") + " \\g (tuples_only=on format=unaligned)"
    return query


class _Sessions:
    def __init__(
        self, api: Any, cid: str, image: SandboxImage, plan: dict[str, Any], s: VideoSettings
    ) -> None:
        self.api, self.cid, self.image, self.plan, self.s = api, cid, image, plan, s
        self.open: dict[str, PsqlSession | ShSession] = {}

    def open_session(self, name: str) -> None:
        if name in self.open:
            return
        decl = self.plan["sessions"][name]
        tmpl = self.image.sessions.get(decl["kind"])
        start = tmpl.start if tmpl else None
        t = self.s.sandbox.command_timeout_s
        if decl["kind"] == "psql":
            self.open[name] = PsqlSession(
                self.api,
                self.cid,
                start or "psql -X -U postgres -d {database}",
                decl.get("database", "postgres"),
                timeout_s=t, ready_s=self.s.sandbox.ready_timeout_s,
                user=self.image.exec_user,
            )  # fmt: skip
        else:
            self.open[name] = ShSession(
                self.api, self.cid, start, decl.get("workdir"), timeout_s=t, user=self.image.exec_user
            )

    def get(self, name: str) -> PsqlSession | ShSession:
        if name not in self.open:
            raise SessionError(f"session {name!r} is not open")
        return self.open[name]

    def close(self, name: str) -> None:
        sess = self.open.pop(name, None)
        if sess:
            sess.close()

    def close_all(self) -> None:
        for name in list(self.open):
            self.close(name)


def _record(res: CommandResult, session: str, seq: int) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "seq": seq, "session": session, "text": res.text, "prompt_before": res.prompt_before,
        "prompt_after": res.prompt_after, "output": res.output, "status": res.status,
        "duration_ms": res.duration_ms,
    }  # fmt: skip
    if res.tx_state is not None:
        rec["tx_state"] = res.tx_state
    if res.exit is not None:
        rec["exit"] = res.exit
    return rec


def run_capture(
    client: docker.DockerClient,
    settings: VideoSettings,
    plan: dict[str, Any],
    script: dict[str, Any],
    *,
    run_id: str = "",
    log_ref: str = "",
) -> tuple[dict[str, Any], str]:
    """Execute `plan` against `script` commands; returns (capture.json content, full log text)."""
    image = settings.sandbox_images[plan["image"]]
    cmds = script_commands(script)
    kinds = {k: v.get("kind", "number") for k, v in (script.get("captures") or {}).items()}
    log: list[str] = []
    started = datetime.now(UTC)
    t_start = time.monotonic()
    commands: dict[str, Any] = {}
    values: dict[str, Any] = {}
    hidden: list[dict[str, Any]] = []
    last_cmd = ""

    def logline(s: str) -> None:
        log.append(f"[{time.monotonic() - t_start:7.2f}] {s}")

    with sandbox_container(client, image, settings, purpose="capture", run_id=run_id) as container:
        wait_ready(container, image, settings.sandbox.ready_timeout_s)
        version = check_version(container, image)
        logline(f"version: {version['output']}")
        if not version["pass"]:
            raise CaptureFailure(
                "version_mismatch", f"{version['output']!r} lacks {version['expect']!r}", "\n".join(log)
            )
        ses = _Sessions(client.api, container.id, image, plan, settings)
        try:
            for name, decl in plan["sessions"].items():
                if decl.get("open_at_start"):
                    ses.open_session(name)
            for i, op in enumerate(plan["ops"]):
                if time.monotonic() - t_start > settings.sandbox.total_timeout_s:
                    raise CaptureFailure("timeout", "capture exceeded total_timeout_s", "\n".join(log))
                kind = op["op"]
                try:
                    if kind == "open":
                        ses.open_session(op["session"])
                    elif kind == "close":
                        ses.close(op["session"])
                    elif kind == "sleep":
                        time.sleep(op["seconds"])
                    elif kind == "setup":
                        r = ses.get(op["session"]).run(op["text"])
                        hidden.append({"session": op["session"], "text": op["text"], "status": r.status})
                        logline(f"setup {op['session']}: {op['text']} -> {r.status}")
                    elif kind == "run":
                        cid = op["cmd"]
                        c = cmds[cid]
                        r = ses.get(c["session"]).run(c["text"])
                        commands[cid] = _record(r, c["session"], len(commands) + 1)
                        last_cmd = cid
                        logline(f"run {cid} [{c['session']}] {c['text']} -> {r.status}")
                        log.extend("    " + ln for ln in r.output)
                    elif kind == "value":
                        sess = ses.get(op["session"])
                        r = sess.run(_value_query(sess.kind, op["query"]))
                        raw = [ln for ln in r.output if ln != ""]
                        values[op["name"]] = {
                            "value": _parse(raw, op.get("parse", "single")),
                            "kind": kinds.get(op["name"], "number"),
                            "session": op["session"], "query": op["query"], "after": last_cmd, "raw": raw,
                            "why_equal": op["why_equal"],
                        }  # fmt: skip
                        logline(f"value {op['name']} = {values[op['name']]['value']!r}")
                except SessionError as exc:
                    log.append(f"op {i} {op}: {exc}")
                    raise CaptureFailure(
                        "not_reproducible", f"op {i} ({kind}): {exc}", "\n".join(log)
                    ) from exc
        finally:
            ses.close_all()

    capture = {
        "format": "manufacture.capture/1",
        "plan_sha256": plan_sha256(plan),
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image": {"key": plan["image"], "ref": image.image, "digest": digest_of(image.image)},
        "version": version,
        "limits": limits_record(settings.sandbox),
        "sessions": {
            n: {k: v for k, v in d.items() if k in ("kind", "database", "workdir")}
            for n, d in plan["sessions"].items()
        },
        "commands": commands,
        "values": values,
        "hidden": hidden,
        "log_ref": log_ref,
    }
    return capture, "\n".join(log) + "\n"


def check_values(capture: dict[str, Any]) -> list[str]:
    """Every value is non-empty and matches its kind (05 section 2.5 step 4)."""
    problems = []
    for name, v in capture["values"].items():
        if v["value"] == "":
            problems.append(f"value {name}: empty (raw {v['raw']!r})")
        elif v["kind"] == "number" and not NUMBER.match(v["value"]):
            problems.append(f"value {name}: {v['value']!r} is not a number")
    return problems


class ScratchSandbox:
    """One scratch container for `sandbox_try`: sessions open on first use; closed with the step."""

    def __init__(
        self, client: docker.DockerClient, settings: VideoSettings, image_key: str, step_id: str
    ) -> None:
        self.client, self.settings, self.image_key, self.step_id = client, settings, image_key, step_id
        self.image = settings.sandbox_images[image_key]
        self._stack: Any = None
        self._container: Any = None
        self._sessions: _Sessions | None = None
        self._plan: dict[str, Any] = {"sessions": {}}
        self.calls = 0

    async def _start(self) -> None:
        import asyncio
        from contextlib import ExitStack

        def go() -> None:
            self._stack = ExitStack()
            self._container = self._stack.enter_context(
                sandbox_container(
                    self.client, self.image, self.settings, purpose="scratch", run_id=self.step_id
                )
            )
            wait_ready(self._container, self.image, self.settings.sandbox.ready_timeout_s)
            self._sessions = _Sessions(
                self.client.api, self._container.id, self.image, self._plan, self.settings
            )

        await asyncio.to_thread(go)

    async def run(self, kind: str, text: str) -> dict[str, Any]:
        import asyncio

        if self._container is None:
            await self._start()
        assert self._sessions is not None  # noqa: S101
        name = f"scratch_{kind}"
        self._plan["sessions"].setdefault(name, {"kind": kind, "database": "postgres"})

        def go() -> dict[str, Any]:
            assert self._sessions is not None  # noqa: S101
            self._sessions.open_session(name)
            r = self._sessions.get(name).run(text)
            return {"output": r.output, "status": r.status}

        self.calls += 1
        return await asyncio.to_thread(go)

    async def close(self) -> None:
        import asyncio

        def go() -> None:
            if self._sessions:
                self._sessions.close_all()
            if self._stack:
                self._stack.close()

        await asyncio.to_thread(go)
        self._container = None
