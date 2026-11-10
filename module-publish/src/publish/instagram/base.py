"""Instagram client abstraction — Fake in tests/default; real Login later."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

# Called with the container id right before the irreversible media_publish call. It raises
# PublishFencedError when this run may no longer publish (timed out, superseded, cancelled).
BeforePublish = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PublishResult:
    external_post_id: str
    url: str
    published_at: datetime


class InstagramClient(Protocol):
    dry_run: bool

    async def publish_reel(
        self,
        *,
        account_id: str,
        video_ref: str,
        caption: str,
        cover_ref: str | None = None,
        intent_id: str | None = None,
        before_publish: BeforePublish | None = None,
    ) -> PublishResult: ...

    async def reconcile(
        self,
        *,
        account_id: str,
        external_post_id: str,
        caption: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Look the post up without publishing anything.

        Returns None when nothing was found and the outcome stays unknown,
        {"status": "published", "external_post_id", "url", "published_at"} when the post exists,
        {"status": "published_unverified"} when the container is PUBLISHED but the media was not matched,
        {"status": "not_published"} when the container can never be published (ERROR/EXPIRED).
        """
        ...


class UnknownOutcomeError(Exception):
    """Publish may or may not have succeeded — caller must reconcile, never blind-resend."""

    def __init__(self, message: str, *, account_id: str, external_post_id: str | None = None) -> None:
        super().__init__(message)
        self.account_id = account_id
        self.external_post_id = external_post_id


class PublishFencedError(Exception):
    """This run lost the right to publish (deadline passed, superseded by a newer fence, cancelled)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
