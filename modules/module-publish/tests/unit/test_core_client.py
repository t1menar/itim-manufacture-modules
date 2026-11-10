from __future__ import annotations

import httpx
import pytest
import respx

from publish.clients.core import CoreClient


@pytest.mark.asyncio
@respx.mock
async def test_progress_sends_fence() -> None:
    route = respx.post("http://core.test/internal/v1/jobs/j1/progress").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = CoreClient("http://core.test", "tok")
    resp = await client.progress("http://core.test/internal/v1/jobs/j1", fence=3, body={"percent": 0})
    assert resp.status_code == 200
    assert route.called
    assert route.calls.last.request.headers["X-Fence"] == "3"
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"
