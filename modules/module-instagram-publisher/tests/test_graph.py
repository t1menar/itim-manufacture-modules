from __future__ import annotations

import httpx
import pytest

from mipub.errors import InstagramAPIError, UnknownOutcomeError
from mipub.graph import Auth, GraphClient

AUTH = Auth("1789", "secret-token")


def client(handler) -> GraphClient:  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GraphClient(client=http, poll_interval_s=0, poll_max_attempts=3)


def make(calls: list[str], *, publish: httpx.Response | None = None, statuses: tuple[str, ...] = ("FINISHED",)):  # type: ignore[no-untyped-def]
    seq = iter(statuses)

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(f"{r.method} {r.url.path}")
        if r.method == "POST" and r.url.path.endswith("/1789/media"):
            return httpx.Response(200, json={"id": "cont1"})
        if r.url.path.endswith("/media_publish"):
            return publish or httpx.Response(200, json={"id": "med1"})
        if r.url.path.endswith("/cont1"):
            return httpx.Response(200, json={"status_code": next(seq, "FINISHED")})
        if r.url.path.endswith("/med1"):
            return httpx.Response(200, json={"id": "med1", "permalink": "https://www.instagram.com/reel/abc/"})
        return httpx.Response(404, json={"error": {"code": 100, "message": "no"}})

    return handler


async def noop(_: str) -> None:
    return None


async def test_publish_flow_order_and_permalink() -> None:
    calls: list[str] = []
    seen: list[str] = []

    async def before(container: str) -> None:
        seen.append(container)
        assert not any("media_publish" in c for c in calls)  # armed before the irreversible call

    done = await client(make(calls, statuses=("IN_PROGRESS", "FINISHED"))).publish_reel(
        AUTH, video_url="https://h/v.mp4", caption="c", cover_url="https://h/c.jpg", before_publish=before
    )
    assert done.url == "https://www.instagram.com/reel/abc/" and seen == ["cont1"]
    assert [c.split()[1].rsplit("/", 1)[1] for c in calls if "POST" in c] == ["media", "media_publish"]


async def test_non_https_video_is_rejected_before_any_call() -> None:
    calls: list[str] = []
    with pytest.raises(InstagramAPIError):
        await client(make(calls)).publish_reel(
            AUTH, video_url="http://h/v.mp4", caption="c", cover_url=None, before_publish=noop
        )
    assert calls == []


async def test_5xx_on_media_publish_is_unknown_and_not_retried() -> None:
    calls: list[str] = []
    c = client(make(calls, publish=httpx.Response(502, text="bad gateway")))
    with pytest.raises(UnknownOutcomeError) as e:
        await c.publish_reel(AUTH, video_url="https://h/v.mp4", caption="c", cover_url=None, before_publish=noop)
    assert e.value.external_post_id == "cont1" and sum("media_publish" in x for x in calls) == 1


async def test_container_error_is_permanent() -> None:
    with pytest.raises(InstagramAPIError) as e:
        await client(make([], statuses=("ERROR",))).publish_reel(
            AUTH, video_url="https://h/v.mp4", caption="c", cover_url=None, before_publish=noop
        )
    assert not e.value.classified.retryable


async def test_poll_timeout_is_unknown() -> None:
    with pytest.raises(UnknownOutcomeError):
        await client(make([], statuses=("IN_PROGRESS",) * 5)).publish_reel(
            AUTH, video_url="https://h/v.mp4", caption="c", cover_url=None, before_publish=noop
        )


async def test_reconcile_published_container_matches_by_caption() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/cont1"):
            return httpx.Response(200, json={"status_code": "PUBLISHED"})
        if r.url.path.endswith("/1789/media"):
            return httpx.Response(200, json={"data": [
                {"id": "x", "caption": "other", "permalink": "https://i/x", "timestamp": "2026-11-11T10:00:00+0000"},
                {"id": "y", "caption": "mine", "permalink": "https://i/y", "timestamp": "2026-11-11T10:00:00+0000"},
            ]})  # fmt: skip
        return httpx.Response(404, json={"error": {"code": 100, "message": "no"}})

    got = await client(handler).reconcile(AUTH, "cont1", "mine")
    assert got is not None and got["external_post_id"] == "y"
    assert (await client(handler).reconcile(AUTH, "cont1", "nobody")) == {
        "status": "published_unverified",
        "container_id": "cont1",
    }


def test_repr_hides_the_token() -> None:
    assert "secret-token" not in repr(AUTH) and "secret-token" not in repr(GraphClient())
