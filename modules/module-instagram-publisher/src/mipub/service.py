"""PublishService: one idempotent publication of an approved post.

Rules, enforced here and not in prompts:
- the ledger row (account, content hash) is written before the irreversible `media_publish`; `published` is
  returned as is and never posted again, even by a new run of the same idea;
- `publishing`/`unknown` rows are reconciled, never resent: still unknown means `attention` for the operator;
- `confirm(container_id)` is asked right before publishing (the platform checks the attempt lease and the
  review approval); a "no" abandons the container and leaves a `cancelled` row that can be published later;
- `failed` and `cancelled` rows may be retried; the retry creates a fresh container.
No database transaction is held across a network call.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mipub.caption import HASHTAGS_MAX, compose_caption
from mipub.db import transaction
from mipub.errors import InstagramAPIError, PublishCancelled, UnknownOutcomeError
from mipub.graph import Auth, Instagram
from mipub.host import MediaHost, VideoHostError
from mipub.models import Account, Ledger

Confirm = Callable[[str], Awaitable[bool]]


class TokenProvider(Protocol):
    async def token(self, account_code: str) -> str: ...


@dataclass(frozen=True, slots=True)
class PublishRequest:
    idea_ref: str
    step_key: str
    account: str
    video_uri: str
    video_sha256: str
    caption: str
    hashtags: list[str] = field(default_factory=list)
    cover_uri: str | None = None


@dataclass(slots=True)
class Outcome:
    status: str  # published | failed | unknown | cancelled
    document: dict[str, Any]
    retryable: bool = False
    attention: bool = False  # unknown outcome: an operator decides


def content_key(req: PublishRequest, caption: str) -> str:
    return hashlib.sha256(f"{req.video_sha256}\n{caption}".encode()).hexdigest()


class PublishService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        instagram: Instagram,
        host: MediaHost,
        tokens: TokenProvider,
        *,
        hashtags_max: int = HASHTAGS_MAX,
    ) -> None:
        self.sm, self.ig, self.host, self.tokens, self.hashtags_max = sm, instagram, host, tokens, hashtags_max

    async def publish(self, req: PublishRequest, confirm: Confirm | None = None) -> Outcome:
        async with transaction(self.sm) as s:
            account = await s.get(Account, req.account)
        if account is None or not account.enabled:
            return Outcome("failed", _doc("account_unavailable", f"account {req.account!r} is unknown or disabled"))
        caption = compose_caption(req.caption, req.hashtags, tags_max=self.hashtags_max)
        key = content_key(req, caption)
        auth = Auth(account.ig_user_id, await self.tokens.token(req.account))

        async with transaction(self.sm) as s:
            row = await _find(s, req.account, key)
            if row is not None and row.status == "published":
                return Outcome("published", row.as_document())
            prior = (row.status, row.container_id, row.started_at) if row is not None else None
        if prior and prior[0] in {"publishing", "unknown"}:
            return await self._reconcile(req, auth, key, caption, prior[1], prior[2])

        async with transaction(self.sm) as s:
            row = await _find(s, req.account, key)
            if row is None:
                s.add(_new(req, key, caption))
            else:
                row.status, row.error, row.step_key, row.container_id = "publishing", None, req.step_key, None
        try:
            video_url = await self.host.public_url(req.video_uri, ".mp4")
            cover_url = await self.host.public_url(req.cover_uri, ".jpg") if req.cover_uri else None
        except VideoHostError as exc:
            await self._set(req, key, "failed", error=str(exc))
            return Outcome("failed", _doc("video_host", str(exc)), retryable=True)

        async def before_publish(container: str) -> None:
            await self._set(req, key, "publishing", container_id=container)  # durable before the irreversible call
            if confirm is not None and not await confirm(container):
                raise PublishCancelled(container)

        try:
            done = await self.ig.publish_reel(
                auth, video_url=video_url, caption=caption, cover_url=cover_url, before_publish=before_publish
            )
        except PublishCancelled:
            await self._set(req, key, "cancelled", error="not confirmed before publishing")
            return Outcome("cancelled", _doc("not_confirmed", "publishing was not confirmed"), retryable=True)
        except UnknownOutcomeError as exc:
            await self._set(req, key, "unknown", container_id=exc.external_post_id, error=str(exc))
            return Outcome("unknown", _doc("unknown_outcome", str(exc)), attention=True)
        except InstagramAPIError as exc:
            await self._set(req, key, "failed", error=exc.classified.message)
            return Outcome(
                "failed", _doc(exc.classified.code, exc.classified.message), retryable=exc.classified.retryable
            )
        row_doc = await self._set(
            req, key, "published", external_post_id=done.external_post_id, url=done.url, published_at=done.published_at
        )
        return Outcome("published", row_doc)

    async def _reconcile(
        self, req: PublishRequest, auth: Auth, key: str, caption: str, container: str | None, since: datetime
    ) -> Outcome:
        found = await self.ig.reconcile(auth, container, caption, since) if container else None
        if found is None or found.get("status") == "published_unverified":
            doc = await self._set(req, key, "unknown", error="outcome still unknown after reconcile")
            return Outcome("unknown", doc, attention=True)
        if found["status"] == "not_published":
            await self._set(req, key, "failed", error=f"container {found.get('container_status')}")
            return Outcome("failed", _doc("container_dead", "the container can never be published"), retryable=True)
        doc = await self._set(
            req, key, "published", external_post_id=found["external_post_id"], url=found["url"],
            published_at=_ts(found.get("published_at")),
        )  # fmt: skip
        return Outcome("published", doc)

    async def _set(self, req: PublishRequest, key: str, status: str, **fields: Any) -> dict[str, Any]:
        async with transaction(self.sm) as s:
            row = await _find(s, req.account, key)
            assert row is not None  # noqa: S101
            row.status = status
            for k, v in fields.items():
                setattr(row, k, v)
            return row.as_document()


async def _find(s: AsyncSession, account: str, key: str) -> Ledger | None:
    return (
        await s.execute(select(Ledger).where(Ledger.account_code == account, Ledger.content_key == key))
    ).scalar_one_or_none()


def _new(req: PublishRequest, key: str, caption: str) -> Ledger:
    return Ledger(
        account_code=req.account, content_key=key, step_key=req.step_key, idea_ref=req.idea_ref,
        status="publishing", caption=caption,
    )  # fmt: skip


def _doc(code: str, message: str) -> dict[str, Any]:
    return {"status": "failed", "code": code, "message": message}


def _ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    try:
        text = str(raw)
        if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":
            text = text[:-2] + ":" + text[-2:]
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


__all__ = ["Confirm", "Outcome", "PublishRequest", "PublishService", "TokenProvider", "content_key"]
