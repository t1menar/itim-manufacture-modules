from __future__ import annotations

import pytest
from sqlalchemy import select

from helpers import FakeInstagram, Host, Tokens
from mipub.caption import compose_caption, shorten_caption
from mipub.models import Account, Ledger
from mipub.service import PublishRequest, PublishService


def req(**over) -> PublishRequest:  # type: ignore[no-untyped-def]
    base = dict(
        idea_ref="idea:1:v1", step_key="run1:publish", account="main", video_uri="s3://b/final.mp4",
        video_sha256="a" * 64, caption="Hook line\n\nSummary.\n\nSource: x", hashtags=["#sql", "db"],
        cover_uri="s3://b/cover.jpg",
    )  # fmt: skip
    return PublishRequest(**{**base, **over})


@pytest.fixture
async def seeded(sm):  # type: ignore[no-untyped-def]
    async with sm() as s, s.begin():
        s.add(Account(code="main", ig_user_id="1789", handle="@itim"))
        s.add(Account(code="off", ig_user_id="1790", enabled=False))
    return sm


def svc(sm, ig, host=None):  # type: ignore[no-untyped-def]
    return PublishService(sm, ig, host or Host(), Tokens())


async def ledger(sm) -> list[Ledger]:  # type: ignore[no-untyped-def]
    async with sm() as s:
        return list((await s.execute(select(Ledger))).scalars())


def test_caption_rules() -> None:
    assert compose_caption("Hi", ["#a", "b"]) == "Hi\n\n#a #b"
    assert compose_caption("Hi", [f"t{i}" for i in range(12)]).count("#") == 8
    long = "Hook\n\n" + "\n".join(f"line number {i} " + "x" * 60 for i in range(30)) + "\n\nSource: repo"
    short = shorten_caption(long)
    assert short.startswith("Hook") and short.endswith("Source: repo") and len(short) <= 580


async def test_publishes_once_and_returns_the_ledger_after(seeded) -> None:  # type: ignore[no-untyped-def]
    ig, host = FakeInstagram(), Host()
    s = svc(seeded, ig, host)
    out = await s.publish(req())
    assert out.status == "published" and out.document["url"].endswith("/m1/")
    assert ig.posts[0]["caption"].endswith("#sql #db") and ig.posts[0]["auth"].access_token == "tok-main"
    assert ig.posts[0]["cover_url"].endswith(".jpg") and len(host.calls) == 2
    again = await s.publish(req(step_key="another-run:publish"))  # a new run, same content: no second post
    assert again.status == "published" and len(ig.posts) == 1 and len(await ledger(seeded)) == 1


async def test_unknown_or_disabled_account_fails(seeded) -> None:  # type: ignore[no-untyped-def]
    for acc in ("nope", "off"):
        out = await svc(seeded, FakeInstagram()).publish(req(account=acc))
        assert out.status == "failed" and out.document["code"] == "account_unavailable"


async def test_confirm_no_abandons_the_container_and_a_later_try_posts(seeded) -> None:  # type: ignore[no-untyped-def]
    ig, s = FakeInstagram(), None
    s = svc(seeded, ig)

    async def no(_: str) -> bool:
        return False

    async def yes(_: str) -> bool:
        return True

    out = await s.publish(req(), confirm=no)
    assert out.status == "cancelled" and out.retryable and not ig.posts
    assert (await ledger(seeded))[0].container_id == "c1"
    out = await s.publish(req(), confirm=yes)
    assert out.status == "published" and len(ig.posts) == 1


async def test_lost_answer_is_unknown_and_never_resent(seeded) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram(fail="unknown_after")
    s = svc(seeded, ig)
    out = await s.publish(req())
    assert out.status == "unknown" and out.attention and len(ig.posts) == 1
    again = await s.publish(req())  # reconcile says nothing: still unknown, no second post
    assert again.status == "unknown" and again.attention and len(ig.posts) == 1 and ig.reconciles == 1


async def test_reconcile_finds_the_post_and_closes_the_ledger(seeded) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram(fail="unknown_after")
    s = svc(seeded, ig)
    await s.publish(req())
    ig.reconciled = {"status": "published", "external_post_id": "m9", "url": "https://instagram.com/reel/m9/",
                     "published_at": "2026-11-11T10:00:00+0000"}  # fmt: skip
    out = await s.publish(req())
    assert out.status == "published" and out.document["external_post_id"] == "m9" and len(ig.posts) == 1


async def test_dead_container_allows_a_fresh_attempt(seeded) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram(fail="unknown_before", reconciled={"status": "not_published", "container_status": "ERROR"})
    s = svc(seeded, ig)
    assert (await s.publish(req())).status == "unknown"
    dead = await s.publish(req())
    assert dead.status == "failed" and dead.retryable and not ig.posts
    assert (await s.publish(req())).status == "published"


async def test_api_errors_carry_retryability(seeded) -> None:  # type: ignore[no-untyped-def]
    for mode, retryable in (("api_fatal", False), ("api_transient", True)):
        out = await svc(seeded, FakeInstagram(fail=mode)).publish(req(video_sha256=mode * 8))
        assert out.status == "failed" and out.retryable is retryable
