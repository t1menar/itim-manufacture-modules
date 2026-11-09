"""B7 tests that need Docker and the agent image (marked `docker`).

Build the image first:  docker build -f agent/Dockerfile -t video-agent:dev .
They skip when there is no daemon or no image. The first test reaches api.anthropic.com through the
egress proxy with a deliberately invalid token and expects Anthropic's real 401.
A run with a real token is described in the README (`mvideo agent-smoke`).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mvideo.agents import launcher
from mvideo.agents.outcomes import classify
from mvideo.agents.workspace import Workspace
from mvideo.net.egress_proxy import start_listener
from mvideo.sandbox.executor import make_client
from tests.test_agents import request, settings
from tests.test_sandbox import _docker_host

IMAGE = "video-agent:dev"
pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def client() -> Any:
    try:
        c = make_client(_docker_host())
        c.ping()
        c.images.get(IMAGE)
        return c
    except Exception as exc:
        pytest.skip(f"needs Docker and the image {IMAGE}: {exc}")


def local_settings() -> Any:
    s = settings()
    return s.model_copy(update={"agent": s.agent.model_copy(update={"image": IMAGE})})


def make_request(step_id: str = "t-b7") -> launcher.AgentRequest:
    req = request("trivial", local_settings(), token="sk-ant-oat01-invalid-test-token")
    req.step_id = step_id
    req.workspace = Workspace.build(claude_md="Write hello to /out/hello.txt.", task_md="x")
    req.prompt = "Write the word hello into /out/hello.txt"
    return req


async def test_invalid_token_gives_auth_failed_through_the_proxy(client: Any) -> None:
    req = make_request("t-b7-auth")
    dl = launcher.DockerLauncher(client, network="bridge", proxy_host="host.docker.internal")
    try:
        res = await dl.run(req)
    finally:
        await dl.cleanup("t-b7-auth")
    assert classify(res.result, res.names).kind == "auth_failed"
    assert res.result["sdk_version"] and res.result["cli_version"]
    assert res.egress_allowed > 0 and res.egress_denied == 0
    assert "sk-ant-oat01-invalid-test-token" not in res.files["_transcript.jsonl"].decode()
    assert client.containers.list(all=True, filters={"label": "manufacture.module=video"}) == []


def test_agent_container_has_no_docker_socket_and_no_module_env(client: Any) -> None:
    req = make_request("t-b7-inspect")
    spec = launcher.container_spec(req, network="bridge", proxy_url="http://host.docker.internal:3200")
    vols = [f"video-ws-t-b7-inspect-{n}" for n in ("work", "job", "in", "ref", "out")]
    for v in vols:
        client.volumes.create(name=v)
    c = client.containers.create(**{k: val for k, val in spec.items() if k != "detach"})
    try:
        info = client.api.inspect_container(c.id)
    finally:
        c.remove(force=True)
        for v in vols:
            client.volumes.get(v).remove(force=True)
    mounts = {m["Destination"] for m in info["Mounts"]}
    assert not any("docker.sock" in m for m in mounts) and mounts == {"/work", "/job", "/in", "/ref", "/out"}
    assert all(m["Type"] in ("volume", "tmpfs") for m in info["Mounts"])
    env = {e.split("=", 1)[0] for e in info["Config"]["Env"]}
    assert not any(k.startswith(("MODULE_", "VIDEO_", "S3_", "DOCKER", "ANTHROPIC_API")) for k in env)
    assert "CLAUDE_CODE_OAUTH_TOKEN" in env
    assert info["HostConfig"]["CapDrop"] == ["ALL"] and info["HostConfig"]["ReadonlyRootfs"] is True
    assert info["HostConfig"]["Privileged"] is False and not info["HostConfig"].get("Binds")


async def test_connect_outside_allowlist_is_refused_and_counted(client: Any) -> None:
    listener = await start_listener(["api.anthropic.com"], (38300, 38310))
    try:
        code = (
            "import urllib.request as u, sys\n"
            "try:\n"
            "    u.urlopen('https://example.com', timeout=10)\n"
            "except Exception as e:\n"
            "    print('refused', type(e).__name__, e)\n"
        )
        box = client.containers.create(
            IMAGE, ["python", "-c", code], network="bridge",
            environment={"HTTPS_PROXY": f"http://host.docker.internal:{listener.port}"},
        )  # fmt: skip

        def go() -> bytes:  # blocking Docker calls must not stall the proxy's event loop
            try:
                box.start()
                box.wait(timeout=60)
                return bytes(box.logs())
            finally:
                box.remove(force=True)

        out = await asyncio.to_thread(go)
    finally:
        await listener.close()
    assert b"refused" in out and b"403" in out
    assert listener.stats.denied >= 1 and listener.stats.allowed == 0
