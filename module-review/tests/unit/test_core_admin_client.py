from __future__ import annotations

from uuid import UUID

import httpx
import pytest
import respx

from review.clients.core_admin import CoreAdminClient


@pytest.mark.asyncio
@respx.mock
async def test_republish_sends_mfa_and_tg_actor() -> None:
    route = respx.post(
        "http://core.test/internal/v1/publish-intents/01900000-0000-7000-8000-000000000001/republish"
    ).mock(return_value=httpx.Response(201, json={"id": "x"}))
    client = CoreAdminClient("http://core.test", "mfa_test_admin_token_xxxxxxxx")
    res = await client.republish(
        UUID("01900000-0000-7000-8000-000000000001"),
        reason="fix",
        base_generation=1,
        telegram_user_id=42,
    )
    assert res.status_code == 201
    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer mfa_test_admin_token_xxxxxxxx"
    assert req.headers["X-Admin-Actor"] == "tg:42"


def test_rejects_non_mfa_token() -> None:
    with pytest.raises(ValueError):
        CoreAdminClient("http://core.test", "mft_module_token_xxxxxxxx")
