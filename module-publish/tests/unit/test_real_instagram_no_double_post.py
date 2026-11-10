"""B6: media_publish is never retried blindly; reconcile only reads (respx, no Meta hosts)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from publish.instagram.base import PublishFencedError, UnknownOutcomeError
from publish.instagram.real import AccountAuth, RealInstagramClient

GRAPH = "https://graph.test"
VER = "v22.0"
IG = "17841400000000000"


async def _resolve(_account_id: str) -> AccountAuth:
    return AccountAuth(ig_user_id=IG, access_token="TEST_IG_TOKEN_NOT_A_SECRET")


@pytest.fixture
def client() -> RealInstagramClient:
    return RealInstagramClient(
        resolve_account=_resolve, graph_base=GRAPH, api_version=VER, poll_interval_s=0.01, poll_max_attempts=5
    )


def _media(mid: str, caption: str, ts: str) -> dict[str, str]:
    return {"id": mid, "permalink": f"https://i/{mid}", "caption": caption, "timestamp": ts}


def _container_ok() -> None:
    respx.get(url__regex=r".*content_publishing_limit.*").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.post(f"{GRAPH}/{VER}/{IG}/media").mock(return_value=httpx.Response(200, json={"id": "c1"}))
    respx.get(f"{GRAPH}/{VER}/c1").mock(return_value=httpx.Response(200, json={"status_code": "FINISHED"}))


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [httpx.Response(500, json={"error": {"message": "oops"}}), httpx.ReadTimeout("lost")],
    ids=["5xx", "timeout"],
)
async def test_media_publish_5xx_or_timeout_is_unknown_and_not_retried(
    client: RealInstagramClient, failure: object
) -> None:
    _container_ok()
    publish = respx.post(f"{GRAPH}/{VER}/{IG}/media_publish")
    if isinstance(failure, Exception):
        publish.mock(side_effect=failure)
    else:
        publish.mock(return_value=failure)
    with pytest.raises(UnknownOutcomeError) as info:
        await client.publish_reel(account_id="acc", video_ref="https://cdn.example/v.mp4", caption="c")
    assert publish.call_count == 1, "media_publish must not be retried after an ambiguous failure"
    assert info.value.external_post_id == "c1"
    assert info.value.account_id == "acc"


@respx.mock
@pytest.mark.asyncio
async def test_before_publish_fence_stops_media_publish(client: RealInstagramClient) -> None:
    _container_ok()
    publish = respx.post(f"{GRAPH}/{VER}/{IG}/media_publish").mock(
        return_value=httpx.Response(200, json={"id": "m1"})
    )

    async def fence(_container: str) -> None:
        raise PublishFencedError("timeout")

    with pytest.raises(PublishFencedError):
        await client.publish_reel(
            account_id="acc", video_ref="https://cdn.example/v.mp4", caption="c", before_publish=fence
        )
    assert not publish.called


@respx.mock
@pytest.mark.asyncio
async def test_reconcile_published_container_matches_caption(client: RealInstagramClient) -> None:
    respx.get(f"{GRAPH}/{VER}/c1").mock(return_value=httpx.Response(200, json={"status_code": "PUBLISHED"}))
    respx.get(f"{GRAPH}/{VER}/{IG}/media").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "m9",
                        "permalink": "https://i/9",
                        "caption": "other",
                        "timestamp": "2026-11-10T10:05:00+0000",
                    },
                    {
                        "id": "m8",
                        "permalink": "https://i/8",
                        "caption": "mine",
                        "timestamp": "2026-11-10T10:01:00+0000",
                    },
                ]
            },
        )
    )
    since = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
    found = await client.reconcile(account_id="acc", external_post_id="c1", caption="mine", since=since)
    assert found is not None
    assert found["status"] == "published"
    assert found["external_post_id"] == "m8"
    publish = respx.post(url__regex=r".*media_publish")
    assert not publish.called


@respx.mock
@pytest.mark.asyncio
async def test_reconcile_states(client: RealInstagramClient) -> None:
    status = respx.get(f"{GRAPH}/{VER}/c1")
    respx.get(f"{GRAPH}/{VER}/{IG}/media").mock(return_value=httpx.Response(200, json={"data": []}))
    status.mock(return_value=httpx.Response(200, json={"status_code": "PUBLISHED"}))
    found = await client.reconcile(account_id="acc", external_post_id="c1", caption="mine")
    assert found == {"status": "published_unverified", "container_id": "c1"}
    status.mock(return_value=httpx.Response(200, json={"status_code": "EXPIRED"}))
    found = await client.reconcile(account_id="acc", external_post_id="c1")
    assert found is not None and found["status"] == "not_published"
    status.mock(return_value=httpx.Response(200, json={"status_code": "FINISHED"}))
    assert await client.reconcile(account_id="acc", external_post_id="c1") is None
