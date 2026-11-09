"""Fake Instagram Login API — no network. Used for local/CI and dry runs."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from publish.instagram.base import PublishResult, UnknownOutcomeError


@dataclass
class FakeInstagramClient:
    """In-memory Instagram Login stand-in. Never opens sockets."""

    dry_run: bool = True
    fail_next: str | None = None  # "transient" | "fatal" | "unknown"
    _seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    posts: list[dict[str, Any]] = field(default_factory=list)

    async def publish_reel(
        self,
        *,
        account_id: str,
        video_ref: str,
        caption: str,
        cover_ref: str | None = None,
        intent_id: str | None = None,
    ) -> PublishResult:
        mode = self.fail_next
        self.fail_next = None
        if mode == "transient":
            raise RuntimeError("fake transient instagram error")
        if mode == "fatal":
            raise RuntimeError("fake fatal instagram error")
        n = next(self._seq)
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
            }
        )
        return PublishResult(external_post_id=external_id, url=url, published_at=at)

    async def reconcile(self, *, account_id: str, external_post_id: str) -> dict[str, Any] | None:
        for p in self.posts:
            if p["account_id"] == account_id and p["external_post_id"] == external_post_id:
                return p
        return None
