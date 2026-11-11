from __future__ import annotations

import httpx
import pytest
from manufacture.testing import call_step as _call_step

from helpers import FakeInstagram, Host, Tokens
from mipub.adapter import EnvTokens, make_app
from mipub.models import Account
from mipub.service import PublishService

CONFIRMS: list[httpx.Request] = []


def core_says(result: str = "ok"):  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        CONFIRMS.append(req)
        return httpx.Response(200, json={"result": result, "attempt_id": "a"})

    return handler


async def call_step(app, data, **kw):  # type: ignore[no-untyped-def]
    return await _call_step(app, data, core=kw.pop("core", core_says()), **kw)


INPUT = {
    "idea_ref": "idea:1:v1", "account": "main", "video": {"ref": "s3://b/final.mp4", "sha256": "a" * 64},
    "cover": {"ref": "s3://b/cover.jpg"}, "post": {"caption": "Hook\n\nSource: x", "hashtags": ["#sql"]},
}  # fmt: skip


async def app_for(sm, ig: FakeInstagram):  # type: ignore[no-untyped-def]
    async with sm() as s, s.begin():
        s.add(Account(code="main", ig_user_id="1789"))
    svc = PublishService(sm, ig, Host(), Tokens())

    async def provider() -> PublishService:
        return svc

    return make_app(provider)


async def test_publishes_and_returns_the_permalink(sm) -> None:  # type: ignore[no-untyped-def]
    res = await call_step(await app_for(sm, FakeInstagram()), INPUT)
    assert res.type == "step.succeeded" and res.payload["output"]["url"].startswith("https://www.instagram.com/reel/")


async def test_retried_step_does_not_post_twice(sm) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram()
    app = await app_for(sm, ig)
    await call_step(app, INPUT)
    again = await call_step(app, INPUT)  # a new run with the same content
    assert again.type == "step.succeeded" and len(ig.posts) == 1


async def test_unknown_outcome_needs_attention_and_is_not_resent(sm) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram(fail="unknown_after")
    app = await app_for(sm, ig)
    res = await call_step(app, INPUT)
    assert res.payload["class"] == "attention" and res.payload["code"] == "unknown_outcome"
    assert (await call_step(app, INPUT)).payload["class"] == "attention" and len(ig.posts) == 1


@pytest.mark.parametrize(("mode", "klass"), [("api_transient", "transient"), ("api_fatal", "fatal")])
async def test_api_errors_map_to_error_classes(sm, mode: str, klass: str) -> None:  # type: ignore[no-untyped-def]
    res = await call_step(await app_for(sm, FakeInstagram(fail=mode)), INPUT)
    assert res.type == "step.failed" and res.payload["class"] == klass


async def test_missing_token_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIPUB_TOKEN_MAIN", raising=False)
    with pytest.raises(Exception, match="MIPUB_TOKEN_MAIN"):
        await EnvTokens().token("main")
    monkeypatch.setenv("MIPUB_TOKEN_MY_ACC", "t")
    assert await EnvTokens().token("my-acc") == "t"


async def test_confirm_is_asked_right_before_media_publish_with_the_step_key(sm) -> None:  # type: ignore[no-untyped-def]
    CONFIRMS.clear()
    ig = FakeInstagram()
    res = await call_step(await app_for(sm, ig), INPUT)
    assert res.succeeded and len(CONFIRMS) == 1 and len(ig.posts) == 1
    assert CONFIRMS[0].url.path.endswith("/confirm") and b"media_publish" in CONFIRMS[0].content


@pytest.mark.parametrize("verdict", ["superseded", "cancelled"])
async def test_refused_confirm_publishes_nothing_and_reports_nothing(sm, verdict: str) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram()
    app = await app_for(sm, ig)
    with pytest.raises(TimeoutError):  # no result is reported for an attempt the core has dropped
        await call_step(app, INPUT, core=core_says(verdict), timeout_s=1)
    assert ig.posts == []


async def test_deadline_too_close_is_transient(sm) -> None:  # type: ignore[no-untyped-def]
    ig = FakeInstagram()
    res = await call_step(await app_for(sm, ig), INPUT, core=core_says("deadline"))
    assert res.payload["class"] == "transient" and res.payload["code"] == "deadline_too_close" and ig.posts == []
