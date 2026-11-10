"""Fake Instagram Login API — no network. Used for local/CI and dry runs."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from publish.instagram.base import BeforePublish, PublishResult, UnknownOutcomeError


@dataclass
class FakeInstagramClient:
    """In-memory Instagram Login stand-in. Never opens sockets."""

    dry_run: bool = True
    # "transient" | "fatal" | "unknown" (nothing posted, outcome lost) |
    # "unknown_after_publish" (posted, but the answer was lost: a 5xx/timeout on media_publish)
    fail_next: str | None = None
    publish_calls: int = 0
    _seq: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    posts: list[dict[str, Any]] = field(default_factory=list)

    async def publish_reel(
        self,
        *,
        account_id: str,
        video_ref: str,
        caption: str,
        cover_ref: str | None = None,
        intent_id: str | None = None,
        before_publish: BeforePublish | None = None,
    ) -> PublishResult:
        mode = self.fail_next
        self.fail_next = None
        if mode == "transient":
            raise RuntimeError("fake transient instagram error")
        if mode == "fatal":
            raise RuntimeError("fake fatal instagram error")
        n = next(self._seq)
        container_id = f"fake_container_{n}"
        if before_publish is not None:
            await before_publish(container_id)
        self.publish_calls += 1
        external_id = f"fake_{account_id[:8]}_{n}"
        url = f"https://www.instagram.com/reel/{external_id}/"
        at = datetime.now(UTC)
        if mode == "unknown":
            # Record nothing durable — reconcile will miss → unknown outcome.
            raise UnknownOutcomeError(
                "fake unknown outcome", account_id=account_id, external_post_id=external_id
            )
        self.posts.append(
            {
                "account_id": account_id,
                "video_ref": video_ref,
                "caption": caption,
                "cover_ref": cover_ref,
                "intent_id": intent_id,
                "external_post_id": external_id,
                "url": url,
                "published_at": at.isoformat(),
                "dry_run": self.dry_run,
                "container_id": container_id,
            }
        )
        if mode == "unknown_after_publish":
            raise UnknownOutcomeError(
                "fake media_publish 5xx after the post went out",
                account_id=account_id,
                external_post_id=container_id,
            )
        return PublishResult(external_post_id=external_id, url=url, published_at=at)

    async def reconcile(
        self,
        *,
        account_id: str,
        external_post_id: str,
        caption: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, Any] | None:
        _ = caption, since
        for p in self.posts:
            if p["account_id"] == account_id and external_post_id in (
                p["external_post_id"],
                p["container_id"],
            ):
                return {**p, "status": "published"}
        return None
