"""Claude Code headless runs (`claude -p --output-format stream-json`) and the subscription usage windows.

Every run reports `rate_limit_event`s: the utilization (0..1) and reset time of the 5-hour and 7-day windows.
`probe()` makes a tiny run on a small model just to read them.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mstudio.settings import Settings, child_env


@dataclass
class Window:
    utilization: float
    resets_at: float  # unix seconds
    status: str = "allowed"


@dataclass
class Usage:
    windows: dict[str, Window] = field(default_factory=dict)
    seen_at: float = 0.0

    def blocking(self, min_left: float) -> tuple[str, Window] | None:
        """The window that says "wait": rejected, or less than `min_left` left. The later reset wins."""
        bad = [(n, w) for n, w in self.windows.items() if w.status != "allowed" or 1 - w.utilization < min_left]
        return max(bad, key=lambda x: x[1].resets_at) if bad else None


def parse_rate_event(ev: dict[str, Any]) -> dict[str, Window]:
    info = ev.get("rate_limit_info") or {}
    out: dict[str, Window] = {}
    for name, w in (info.get("unifiedWindows") or {}).items():
        out[name] = Window(
            float(w.get("utilization") or 0), float(w.get("resetsAt") or 0), str(w.get("status") or "allowed")
        )
    if not out and info.get("rateLimitType"):  # older shape: one window
        out[str(info["rateLimitType"])] = Window(
            float(info.get("utilization") or 0), float(info.get("resetsAt") or 0), str(info.get("status") or "allowed")
        )
    return out


class LimitHit(Exception):
    """The subscription said no (or will soon): wait until `resets_at`, then resume the same session."""

    def __init__(self, window: str, resets_at: float) -> None:
        super().__init__(f"usage window {window} is exhausted until {time.ctime(resets_at)}")
        self.window = window
        self.resets_at = resets_at


class StageFailed(Exception):
    """Claude Code finished with an error (not a usage limit)."""


@dataclass
class RunResult:
    session_id: str
    text: str
    cost_usd: float
    usage: dict[str, Any]


_LIMIT_TEXT = re.compile(r"usage limit|rate limit|limit (?:reached|exceeded)|out of (?:extra )?usage", re.I)

Spawn = Callable[..., Awaitable[asyncio.subprocess.Process]]


class Claude:
    def __init__(self, settings: Settings, spawn: Spawn | None = None) -> None:
        self.s = settings
        self.usage = Usage()
        self._spawn: Spawn = spawn or asyncio.create_subprocess_exec

    def _cmd(self, prompt: str, *, model: str, session_id: str, resume: bool, add_dirs: list[Path]) -> list[str]:
        cmd = [
            self.s.claude_bin, "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
            "--permission-mode", self.s.permission_mode, "--permission-prompts", "none",
        ]  # fmt: skip
        if model == self.s.model and self.s.effort:
            cmd += ["--effort", self.s.effort]
        cmd += ["--resume", session_id] if resume else ["--session-id", session_id]
        for d in add_dirs:
            cmd += ["--add-dir", str(d)]
        return cmd

    async def run(
        self, prompt: str, *, cwd: Path, log: Path, session_id: str | None = None, resume: bool = False,
        model: str | None = None, add_dirs: list[Path] | None = None, persist: bool = True,
    ) -> RunResult:  # fmt: skip
        """One headless turn. Raises LimitHit or StageFailed. `resume=True` continues `session_id`."""
        sid = session_id or str(uuid.uuid4())
        cmd = self._cmd(prompt, model=model or self.s.model, session_id=sid, resume=resume, add_dirs=add_dirs or [])
        if not persist:
            cmd.append("--no-session-persistence")
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = await self._spawn(
            *cmd, cwd=str(cwd), env=child_env(), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, limit=64 * 1024 * 1024,
        )  # fmt: skip
        result: dict[str, Any] | None = None
        tail: list[str] = []
        assert proc.stdout is not None
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"mstudio": "start", "at": time.time(), "session": sid, "resume": resume}) + "\n")
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                fh.write(line + "\n")
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    tail = (tail + [line])[-20:]
                    continue
                kind = ev.get("type")
                if kind == "rate_limit_event":
                    self.usage.windows.update(parse_rate_event(ev))
                    self.usage.seen_at = time.time()
                elif kind == "result":
                    result = ev
                elif kind == "system" and ev.get("subtype") == "init" and ev.get("session_id"):
                    sid = str(ev["session_id"])
        code = await proc.wait()
        if result is not None and not result.get("is_error") and result.get("subtype") == "success":
            return RunResult(sid, str(result.get("result") or ""), float(result.get("total_cost_usd") or 0),
                             dict(result.get("usage") or {}))  # fmt: skip
        text = str((result or {}).get("result") or "") + "\n" + "\n".join(tail)
        rejected = [(n, w) for n, w in self.usage.windows.items() if w.status != "allowed"]
        if rejected or _LIMIT_TEXT.search(text):
            name, w = max(rejected, key=lambda x: x[1].resets_at) if rejected else ("five_hour", self._next_reset())
            raise LimitHit(name, w.resets_at if isinstance(w, Window) else w)
        raise StageFailed(f"claude exited {code}: {text.strip()[-1500:] or 'no result event'}")

    def _next_reset(self) -> float:
        w = self.usage.windows.get("five_hour")
        return w.resets_at if w and w.resets_at > time.time() else time.time() + 3600

    async def probe(self, cwd: Path, log: Path) -> Usage:
        """A tiny run on the small model, only to read the usage windows."""
        try:
            await self.run("Reply with OK.", cwd=cwd, log=log, model=self.s.probe_model, persist=False)
        except LimitHit:
            pass  # the windows are recorded either way
        return self.usage
