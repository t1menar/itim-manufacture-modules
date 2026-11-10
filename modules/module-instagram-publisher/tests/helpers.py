from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mipub.errors import InstagramAPIError, UnknownOutcomeError
from mipub.graph import Auth, BeforePublish, Published


class FakeInstagram:
    """`fail`: None | unknown_before | unknown_after | api_fatal | api_transient; `reconciled` answers reconcile()."""

    def __init__(self, fail: str | None = None, reconciled: dict[str, Any] | None = None) -> None:
        self.fail, self.reconciled, self.posts, self.reconciles = fail, reconciled, [], 0  # type: ignore[var-annotated]

    async def publish_reel(
        self, auth: Auth, *, video_url: str, caption: str, cover_url: str | None, before_publish: BeforePublish
    ) -> Published:
        from mipub.errors import ClassifiedError  # noqa: PLC0415

        mode, self.fail = self.fail, None
        if mode in {"api_fatal", "api_transient"}:
            raise InstagramAPIError(ClassifiedError("instagram_auth", mode == "api_transient", "boom"))
        container = f"c{len(self.posts) + 1}"
        await before_publish(container)
        if mode == "unknown_before":
            raise UnknownOutcomeError("lost", external_post_id=container)
        self.posts.append({"auth": auth, "video_url": video_url, "caption": caption, "cover_url": cover_url})
        if mode == "unknown_after":
            raise UnknownOutcomeError("5xx after publish", external_post_id=container)
        return Published(
            f"m{len(self.posts)}", f"https://www.instagram.com/reel/m{len(self.posts)}/", datetime.now(UTC)
        )

    async def reconcile(
        self, auth: Auth, external_post_id: str, caption: str | None = None, since: datetime | None = None
    ) -> dict[str, Any] | None:
        self.reconciles += 1
        return self.reconciled


class Host:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def public_url(self, uri: str, ext: str) -> str:
        self.calls.append((uri, ext))
        return uri if uri.startswith("https://") else f"https://cdn.example/{abs(hash(uri)) % 10**6}{ext}"


class Tokens:
    async def token(self, account_code: str) -> str:
        return "tok-" + account_code
