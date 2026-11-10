"""The module keeps itself `up` in the core with periodic heartbeats."""

from __future__ import annotations

import asyncio

import httpx
import respx

from mvideo.heartbeat import Heartbeat


@respx.mock
async def test_beat_sends_the_module_token() -> None:
    route = respx.post("http://core.test/internal/v1/modules/self/heartbeat").mock(
        return_value=httpx.Response(200, json={})
    )
    assert await Heartbeat("http://core.test/", "mft_token").beat() is True
    assert route.calls.last.request.headers["authorization"] == "Bearer mft_token"


@respx.mock
async def test_failures_do_not_stop_the_loop() -> None:
    route = respx.post("http://core.test/internal/v1/modules/self/heartbeat")
    route.side_effect = [httpx.ConnectError("down"), httpx.Response(401), httpx.Response(200, json={})]
    hb = Heartbeat("http://core.test", "t", interval_s=0.01)
    hb.start()
    for _ in range(100):
        if route.call_count >= 3:
            break
        await asyncio.sleep(0.02)
    await hb.stop()
    assert route.call_count >= 3
