"""Fake Instagram Login API — no network. Used for local/CI and dry runs."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class FakePublishResult:
    external_post_id: str
    url: str
    published_at: datetime


@dataclass
class FakeInstagramClient:
    """In-memory Instagram Login stand-in. Never opens sockets."""

    dry_run: bool = True
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
    ) -> FakePublishResult:
        n = next(self._seq)
        external_id = f"fake_{account_id}_{n}"
        url = f"https://www.instagram.com/reel/{external_id}/"
        at = datetime.now(UTC)
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
        return FakePublishResult(external_post_id=external_id, url=url, published_at=at)

    async def reconcile(self, *, account_id: str, external_post_id: str) -> dict[str, Any] | None:
        """Look up a previously faked post (unknown-outcome reconcile stub)."""
        for p in self.posts:
            if p["account_id"] == account_id and p["external_post_id"] == external_post_id:
                return p
        return None
