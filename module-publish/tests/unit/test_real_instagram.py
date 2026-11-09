"""Real Instagram Graph client against respx mock — never hits Meta hosts."""

from __future__ import annotations

import httpx
import pytest
import respx

from publish.instagram.errors import classify_graph_error
from publish.instagram.real import (
    AccountAuth,
    RealInstagramClient,
    _require_public_https_url,
)

GRAPH = "https://graph.test"
VER = "v22.0"
IG = "17841400000000000"
TOKEN = "TEST_IG_TOKEN_NOT_A_SECRET"


async def _resolve(_account_id: str) -> AccountAuth:
    return AccountAuth(ig_user_id=IG, access_token=TOKEN)


@pytest.fixture
def client() -> RealInstagramClient:
    return RealInstagramClient(
        resolve_account=_resolve,
        graph_base=GRAPH,
        api_version=VER,
        poll_interval_s=0.01,
        poll_max_attempts=5,
        timeout_s=5.0,
    )


@respx.mock
@pytest.mark.asyncio
async def test_publish_reel_happy_path(client: RealInstagramClient) -> None:
    respx.get(f"{GRAPH}/{VER}/{IG}/content_publishing_limit").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"quota_usage": 1, "config": {"quota_total": 100, "quota_duration": 86400}}]},
        )
    )
    respx.post(f"{GRAPH}/{VER}/{IG}/media").mock(return_value=httpx.Response(200, json={"id": "container1"}))
    status = respx.get(f"{GRAPH}/{VER}/container1")
    status.side_effect = [
        httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
        httpx.Response(200, json={"status_code": "FINISHED"}),
    ]
    respx.post(f"{GRAPH}/{VER}/{IG}/media_publish").mock(
        return_value=httpx.Response(200, json={"id": "media99"})
    )
    respx.get(f"{GRAPH}/{VER}/media99").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "media99",
                "permalink": "https://www.instagram.com/reel/ABC/",
                "timestamp": "2026-11-09T12:00:00+0000",
            },
        )
    )
    result = await client.publish_reel(
        account_id="0193a000-0000-7000-8000-000000000001",
        video_ref="https://cdn.example/reel.mp4",
        caption="hello #pg",
    )
    assert result.external_post_id == "media99"
    assert "instagram.com/reel" in result.url
    assert TOKEN not in repr(client)


@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_then_success(client: RealInstagramClient) -> None:
    respx.get(url__regex=r".*content_publishing_limit.*").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    media = respx.post(f"{GRAPH}/{VER}/{IG}/media")
    media.side_effect = [
        httpx.Response(
            400,
            json={"error": {"message": "rate", "code": 4, "error_subcode": 2207042}},
        ),
        httpx.Response(200, json={"id": "c2"}),
    ]
    respx.get(f"{GRAPH}/{VER}/c2").mock(return_value=httpx.Response(200, json={"status_code": "FINISHED"}))
    respx.post(f"{GRAPH}/{VER}/{IG}/media_publish").mock(return_value=httpx.Response(200, json={"id": "m2"}))
    respx.get(f"{GRAPH}/{VER}/m2").mock(
        return_value=httpx.Response(200, json={"id": "m2", "permalink": "https://www.instagram.com/reel/x/"})
    )
    result = await client.publish_reel(account_id="a", video_ref="https://cdn.example/v.mp4", caption="c")
    assert result.external_post_id == "m2"


@respx.mock
@pytest.mark.asyncio
async def test_container_error_is_permanent(client: RealInstagramClient) -> None:
    respx.get(url__regex=r".*content_publishing_limit.*").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.post(f"{GRAPH}/{VER}/{IG}/media").mock(return_value=httpx.Response(200, json={"id": "bad"}))
    respx.get(f"{GRAPH}/{VER}/bad").mock(return_value=httpx.Response(200, json={"status_code": "ERROR"}))
    with pytest.raises(RuntimeError, match="container"):
        await client.publish_reel(account_id="a", video_ref="https://cdn.example/v.mp4", caption="c")


@respx.mock
@pytest.mark.asyncio
async def test_reconcile_by_media_id(client: RealInstagramClient) -> None:
    respx.get(f"{GRAPH}/{VER}/media99").mock(
        return_value=httpx.Response(
            200,
            json={"id": "media99", "permalink": "https://www.instagram.com/reel/ABC/"},
        )
    )
    found = await client.reconcile(account_id="a", external_post_id="media99")
    assert found is not None
    assert found["external_post_id"] == "media99"


def test_require_public_https() -> None:
    assert _require_public_https_url("https://cdn.example/a.mp4").startswith("https://")
    with pytest.raises(RuntimeError, match="MinIO"):
        _require_public_https_url("s3://bucket/key.mp4")
    with pytest.raises(RuntimeError, match="https"):
        _require_public_https_url("http://cdn.example/a.mp4")


def test_classify_quota() -> None:
    c = classify_graph_error(
        status_code=400,
        body={"error": {"code": 9, "error_subcode": 2207042, "message": "quota"}},
    )
    assert c.retryable and c.code == "instagram_rate_limit"
