"""Long-lived command sessions inside a sandbox container.

One `docker exec -i` process per session. `psql` runs on a pseudo terminal with a prompt made of
sentinels, so the end of each command and the transaction state (`%x`) are read from the prompt.
`sh` runs `bash` on pipes and prints a sentinel with `$?` after each command. Output of both
streams is merged in order.
"""

from __future__ import annotations

import contextlib
import re
import select
import shlex
import socket
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

PROMPT_OPEN = "@@P@@"
PROMPT_CLOSE = "@@E@@"
PROMPT_CONT = "@@C@@"
SH_PROMPT = "$ "


class SessionError(RuntimeError):
    pass


class SessionTimeout(SessionError):
    pass


@dataclass(slots=True)
class CommandResult:
    text: str
    output: list[str]
    status: str  # "ok" | "error"
    prompt_before: str
    prompt_after: str
    duration_ms: int
    tx_state: str | None = None  # psql: idle | in_tx | failed
    exit: int | None = None  # sh


@dataclass(slots=True)
class _Stream:
    """A socket of `exec_start` with a read buffer; demultiplexes the 8-byte frames when not a tty."""

    sock: socket.socket
    tty: bool
    buf: bytearray = field(default_factory=bytearray)
    raw: bytearray = field(default_factory=bytearray)
    closed: bool = False

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def _fill(self, timeout: float) -> bool:
        ready, _, _ = select.select([self.sock], [], [], max(timeout, 0))
        if not ready:
            return False
        chunk = self.sock.recv(65536)
        if not chunk:
            self.closed = True
            return True
        if self.tty:
            self.buf += chunk
            return True
        self.raw += chunk
        while len(self.raw) >= 8:
            size = struct.unpack(">I", bytes(self.raw[4:8]))[0]
            if len(self.raw) < 8 + size:
                break
            self.buf += self.raw[8 : 8 + size]
            del self.raw[: 8 + size]
        return True

    def read_until(self, markers: list[bytes], timeout: float) -> tuple[bytes, bytes]:
        """Everything before the first of `markers`, and which one; consumes through the marker."""
        deadline = time.monotonic() + timeout
        while True:
            hits = [(self.buf.find(m), m) for m in markers if self.buf.find(m) != -1]
            if hits:
                at, m = min(hits)
                data = bytes(self.buf[:at])
                del self.buf[: at + len(m)]
                return data, m
            if self.closed:
                raise SessionError("session closed: " + bytes(self.buf)[-300:].decode("utf-8", "replace"))
            left = deadline - time.monotonic()
            if left <= 0:
                raise SessionTimeout(f"no prompt after {timeout:.0f} s")
            self._fill(min(left, 0.5))


def _lines(raw: bytes) -> list[str]:
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return [ln.expandtabs(8) for ln in text.split("\n")] if text != "" else []


def _open_exec(
    api: Any,
    container_id: str,
    cmd: list[str],
    *,
    tty: bool,
    workdir: str | None,
    env: dict[str, str] | None,
    user: str | None = None,
) -> _Stream:
    ex = api.exec_create(
        container_id,
        cmd,
        stdin=True,
        stdout=True,
        stderr=True,
        tty=tty,
        workdir=workdir,
        environment=env,
        user=user or "",
    )
    raw = api.exec_start(ex["Id"], socket=True, tty=tty)
    sock = getattr(raw, "_sock", raw)
    return _Stream(sock, tty)


class PsqlSession:
    kind = "psql"

    def __init__(
        self,
        api: Any,
        container_id: str,
        start: str,
        database: str,
        *,
        timeout_s: float,
        ready_s: float,
        user: str | None = None,
    ) -> None:
        self.database = database
        self.timeout_s = timeout_s
        argv = shlex.split(start.replace("{database}", database))
        if "-X" not in argv:
            argv.insert(1, "-X")
        argv += [
            "-n",
            "-P",
            "pager=off",
            "-v",
            f"PROMPT1={PROMPT_OPEN}%/%R%x%# {PROMPT_CLOSE}",
            "-v",
            f"PROMPT2={PROMPT_CONT}",
        ]
        script = "stty -echo -onlcr; exec " + shlex.join(argv)
        self.stream = _open_exec(
            api, container_id, ["sh", "-c", script], tty=True, workdir=None, env=None, user=user
        )
        self.prompt = self._read_prompt(ready_s)

    def _read_prompt(self, timeout: float) -> str:
        data, _ = self.stream.read_until([PROMPT_CLOSE.encode()], timeout)
        text = data.decode("utf-8", "replace")
        return text.rsplit(PROMPT_OPEN, 1)[-1]

    def run(self, text: str) -> CommandResult:
        before = self.prompt
        t0 = time.monotonic()
        self.stream.write(text.encode() + b"\n")
        data, marker = self.stream.read_until([PROMPT_CLOSE.encode(), PROMPT_CONT.encode()], self.timeout_s)
        if marker == PROMPT_CONT.encode():
            raise SessionError(f"incomplete command (psql waits for more input): {text!r}")
        head, _, prompt = data.decode("utf-8", "replace").rpartition(PROMPT_OPEN)
        self.prompt = prompt
        output = _lines(head.encode())
        tx = (
            "failed"
            if "!" in prompt.rsplit("=", 1)[-1]
            else "in_tx"
            if "*" in prompt.rsplit("=", 1)[-1]
            else "idle"
        )
        status = "error" if any(re.match(r"ERROR:", ln) for ln in output) else "ok"
        return CommandResult(
            text, output, status, before, prompt, round((time.monotonic() - t0) * 1000), tx_state=tx
        )

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.stream.write(b"\\q\n")
        self.stream.sock.close()


class ShSession:
    kind = "sh"

    def __init__(
        self,
        api: Any,
        container_id: str,
        start: str | None,
        workdir: str | None,
        *,
        timeout_s: float,
        user: str | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        argv = start or "bash --noprofile --norc"
        self.stream = _open_exec(
            api,
            container_id,
            ["sh", "-c", f"exec {argv} 2>&1"],
            tty=False,
            workdir=workdir,
            env=None,
            user=user,
        )
        self.prompt = SH_PROMPT

    def run(self, text: str) -> CommandResult:
        token = uuid.uuid4().hex[:12]
        t0 = time.monotonic()
        self.stream.write(f"{text}\nprintf '\\001@@END:{token}:%d@@\\n' $?\n".encode())
        marker = f"\x01@@END:{token}:".encode()
        data, _ = self.stream.read_until([marker], self.timeout_s)
        code_raw, _ = self.stream.read_until([b"@@\n"], 5)
        code = int(code_raw)
        return CommandResult(
            text, _lines(data), "ok" if code == 0 else "error", SH_PROMPT, SH_PROMPT,
            round((time.monotonic() - t0) * 1000), exit=code,
        )  # fmt: skip

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.stream.write(b"exit\n")
        self.stream.sock.close()
