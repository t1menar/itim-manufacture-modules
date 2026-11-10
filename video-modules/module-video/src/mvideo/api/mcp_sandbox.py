"""HTTP MCP server `sandbox` with the tool `sandbox_try` (03 section 5.4, 05 section 2.5).

The capture agent may try commands in a scratch container of the same sandbox image to learn how
outputs look. One scratch sandbox per capture step, started lazily, destroyed at step end; its
output is returned as data and never used in the video. Calls carry a per-step bearer token and are
reachable only from the agent network. Minimal JSON-RPC over HTTP (`initialize`, `tools/list`,
`tools/call`).
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

PROTOCOL = "2025-03-26"
TOOL = {
    "name": "sandbox_try",
    "description": (
        "Run one command in a scratch sandbox (same image, no network) and return its output. Use it to "
        "see how outputs look and which queries give the values the debugger shows. Output is for you "
        "only; it is never used in the video."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_kind": {"type": "string", "enum": ["psql", "sh"]},
            "text": {"type": "string", "maxLength": 2000},
            "database": {"type": "string"},
        },
        "required": ["session_kind", "text"],
    },
}


class Scratch(Protocol):
    async def run(self, kind: str, text: str) -> dict[str, Any]: ...
    async def close(self) -> None: ...


class ScratchRegistry:
    """Tokens of running capture steps and their scratch sandboxes."""

    def __init__(self, factory: Any = None) -> None:
        self._factory = factory  # async (step_id) -> Scratch; a step may bring its own (settings are per job)
        self._own: dict[str, Any] = {}
        self._steps: dict[str, tuple[str, Scratch | None]] = {}
        self._lock = asyncio.Lock()

    def register(self, step_id: str, factory: Any = None) -> str:
        token = secrets.token_urlsafe(24)
        if factory is not None:
            self._own[token] = factory
        self._steps[token] = (step_id, None)
        return token

    async def get(self, token: str) -> Scratch | None:
        async with self._lock:
            entry = self._steps.get(token)
            if entry is None:
                return None
            step_id, scratch = entry
            if scratch is None:
                scratch = await (self._own.get(token) or self._factory)(step_id)
                self._steps[token] = (step_id, scratch)
            return scratch

    def known(self, token: str) -> bool:
        return token in self._steps

    async def end(self, token: str) -> None:
        """Step end: forget the token and destroy the scratch sandbox."""
        entry = self._steps.pop(token, None)
        if entry and entry[1] is not None:
            await entry[1].close()


router = APIRouter()


def _rpc(id_: Any, result: Any = None, error: tuple[int, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": id_}
    if error:
        body["error"] = {"code": error[0], "message": error[1]}
    else:
        body["result"] = result
    return JSONResponse(body)


@router.post("/mcp/sandbox")
async def mcp_sandbox(request: Request) -> Response:
    reg: ScratchRegistry | None = getattr(request.app.state, "scratch", None)
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if reg is None or not reg.known(token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    msg = await request.json()
    method, id_ = msg.get("method"), msg.get("id")
    if id_ is None:  # notification
        return Response(status_code=202)
    if method == "initialize":
        return _rpc(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "sandbox", "version": "1.0.0"}})  # fmt: skip
    if method == "tools/list":
        return _rpc(id_, {"tools": [TOOL]})
    if method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != "sandbox_try":
            return _rpc(id_, error=(-32602, "unknown tool"))
        args = params.get("arguments") or {}
        if args.get("session_kind") not in ("psql", "sh") or not isinstance(args.get("text"), str):
            return _rpc(id_, error=(-32602, "session_kind (psql|sh) and text are required"))
        scratch = await reg.get(token)
        assert scratch is not None  # noqa: S101
        try:
            out = await scratch.run(args["session_kind"], args["text"])
            text, is_error = "\n".join(out.get("output", [])) or "(no output)", out.get("status") == "error"
        except Exception as exc:
            text, is_error = f"sandbox error: {exc}", True
        return _rpc(id_, {"content": [{"type": "text", "text": text}], "isError": is_error})
    return _rpc(id_, error=(-32601, f"method not found: {method}"))
