"""Instagram client abstraction — Fake in tests/default; real Login later."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


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
    ) -> PublishResult: ...

    async def reconcile(self, *, account_id: str, external_post_id: str) -> dict[str, Any] | None: ...


class UnknownOutcomeError(Exception):
    """Publish may or may not have succeeded — caller must reconcile, never blind-resend."""

    def __init__(self, message: str, *, account_id: str, external_post_id: str | None = None) -> None:
        super().__init__(message)
        self.account_id = account_id
        self.external_post_id = external_post_id
