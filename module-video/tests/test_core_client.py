from __future__ import annotations

import httpx
import pytest
import respx

from mvideo.core_client import (
    CoreClient,
    CoreError,
    CoreRejected,
    CoreUnavailable,
    CredentialError,
    JobCall,
)

BASE = "http://core:8080/internal/v1/jobs/j1"
CALL = JobCall(job_id="j1", production_id="p1", base_url=BASE, traceparent="00-abc-def-01")


class Clock:
    """Virtual time: sleeping advances the clock, so backoff tests run instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def client(clock: Clock, **kw: float) -> CoreClient:
    return CoreClient("http://core:8080", "tok", sleep=clock.sleep, monotonic=clock.monotonic, **kw)


@respx.mock
async def test_callback_carries_auth_and_tracing_headers() -> None:
    route = respx.post(f"{BASE}/progress").respond(204)
    await client(Clock()).progress(CALL, 40, "render", "chunk 4/10")
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["x-production-id"] == "p1"
    assert req.headers["traceparent"] == "00-abc-def-01"
    assert req.read() == b'{"percent":40,"step":"render","message":"chunk 4/10"}'


@respx.mock
async def test_retries_5xx_with_exponential_backoff_then_succeeds() -> None:
    route = respx.post(f"{BASE}/result").mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(500), httpx.Response(200)]
    )
    clock = Clock()
    await client(clock).result(CALL, {"output": {}})
    assert route.call_count == 4
    assert clock.sleeps == [1.0, 2.0, 4.0]


@respx.mock
async def test_retries_network_errors() -> None:
    route = respx.post(f"{BASE}/fail").mock(side_effect=[httpx.ConnectError("down"), httpx.Response(200)])
    clock = Clock()
    await client(clock).fail(CALL, {"class": "fatal"})
    assert route.call_count == 2


@respx.mock
async def test_backoff_is_capped_at_60_seconds() -> None:
    respx.post(f"{BASE}/result").mock(side_effect=[httpx.Response(503)] * 9 + [httpx.Response(200)])
    clock = Clock()
    await client(clock).result(CALL, {})
    assert clock.sleeps == [1, 2, 4, 8, 16, 32, 60, 60, 60]


@respx.mock
async def test_gives_up_after_the_retry_budget() -> None:
    route = respx.post(f"{BASE}/result").respond(503)
    clock = Clock()
    with pytest.raises(CoreUnavailable):
        await client(clock, give_up_s=900).result(CALL, {})
    assert clock.now <= 900
    assert route.call_count > 10


@respx.mock
async def test_progress_does_not_retry_for_long() -> None:
    respx.post(f"{BASE}/progress").respond(503)
    clock = Clock()
    with pytest.raises(CoreUnavailable):
        await client(clock).progress(CALL, 1, "x", "y")
    assert clock.now <= 10


@respx.mock
async def test_409_stops_retries_immediately() -> None:
    route = respx.post(f"{BASE}/result").respond(409)
    with pytest.raises(CoreRejected):
        await client(Clock()).result(CALL, {})
    assert route.call_count == 1


@respx.mock
async def test_other_4xx_is_not_retried() -> None:
    route = respx.post(f"{BASE}/result").respond(422, json={"code": "output_invalid"})
    with pytest.raises(CoreError):
        await client(Clock()).result(CALL, {})
    assert route.call_count == 1


@respx.mock
async def test_credential_read() -> None:
    route = respx.get("http://core:8080/internal/v1/credentials/cred%3Aclaude-subscription").respond(
        200,
        json={
            "ref": "cred:claude-subscription",
            "kind": "claude_oauth_token",
            "value": "s3cret",
            "expires_at": None,
        },
    )
    cred = await client(Clock()).get_credential(CALL, "cred:claude-subscription")
    assert (cred.kind, cred.value) == ("claude_oauth_token", "s3cret")
    assert route.calls.last.request.headers["x-job-id"] == "j1"
    assert "s3cret" not in repr(cred)


@respx.mock
@pytest.mark.parametrize(("status", "reason"), [(404, "not_found"), (403, "forbidden"), (401, "forbidden")])
async def test_credential_errors(status: int, reason: str) -> None:
    respx.get("http://core:8080/internal/v1/credentials/cred%3Ax").respond(status)
    with pytest.raises(CredentialError) as err:
        await client(Clock()).get_credential(CALL, "cred:x")
    assert err.value.reason == reason
