from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mvideo.api import mcp_sandbox


class FakeScratch:
    def __init__(self) -> None:
        self.closed = False
        self.seen: list[tuple[str, str]] = []

    async def run(self, kind: str, text: str) -> dict[str, Any]:
        self.seen.append((kind, text))
        return (
            {"output": ["16384"], "status": "ok"}
            if text != "boom"
            else {"output": ["ERROR: x"], "status": "error"}
        )

    async def close(self) -> None:
        self.closed = True


def make() -> tuple[TestClient, mcp_sandbox.ScratchRegistry, FakeScratch]:
    scratch = FakeScratch()

    async def factory(step_id: str) -> FakeScratch:
        return scratch

    app = FastAPI()
    app.state.scratch = reg = mcp_sandbox.ScratchRegistry(factory)
    app.include_router(mcp_sandbox.router)
    return TestClient(app), reg, scratch


def rpc(
    client: TestClient, token: str, method: str, params: dict[str, Any] | None = None, id_: int | None = 1
) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        body["id"] = id_
    if params is not None:
        body["params"] = params
    return client.post("/mcp/sandbox", json=body, headers={"Authorization": f"Bearer {token}"})


def test_requires_a_known_step_token() -> None:
    client, reg, _ = make()
    assert rpc(client, "nope", "initialize").status_code == 401
    token = reg.register("s1")
    assert rpc(client, token, "initialize").json()["result"]["serverInfo"]["name"] == "sandbox"


def test_list_and_call_and_scratch_is_lazy_and_closed_at_step_end() -> None:
    import asyncio

    client, reg, scratch = make()
    token = reg.register("s1")
    assert rpc(client, token, "tools/list").json()["result"]["tools"][0]["name"] == "sandbox_try"
    assert rpc(client, token, "notifications/initialized", id_=None).status_code == 202
    assert scratch.seen == []  # nothing started yet
    r = rpc(
        client,
        token,
        "tools/call",
        {"name": "sandbox_try", "arguments": {"session_kind": "psql", "text": "SELECT 1"}},
    )
    res = r.json()["result"]
    assert res["content"][0]["text"] == "16384" and res["isError"] is False
    bad = rpc(
        client,
        token,
        "tools/call",
        {"name": "sandbox_try", "arguments": {"session_kind": "psql", "text": "boom"}},
    )
    assert bad.json()["result"]["isError"] is True
    assert rpc(
        client, token, "tools/call", {"name": "sandbox_try", "arguments": {"session_kind": "x", "text": "y"}}
    ).json()["error"]
    asyncio.run(reg.end(token))
    assert scratch.closed and rpc(client, token, "initialize").status_code == 401
