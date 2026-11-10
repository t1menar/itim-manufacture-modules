"""Instagram Graph API Reels client: container -> poll -> (confirm) -> media_publish -> permalink.

Upload is always by public HTTPS `video_url` (Meta's resumable upload takes only ~1.7 MB per request, so
the file goes to a web host first, see `host.py`). Tokens are never logged. `media_publish` is never retried:
a lost answer is an unknown outcome that is reconciled, not resent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from mipub.errors import ClassifiedError, InstagramAPIError, UnknownOutcomeError, classify_graph_error

log = logging.getLogger(__name__)

DEFAULT_API_VERSION = "v27.0"
DEFAULT_GRAPH_BASE = "https://graph.facebook.com"  # system-user tokens (EAA...); Instagram-Login: graph.instagram.com

BeforePublish = Callable[[str], Awaitable[None]]  # container id, called right before the irreversible call


@dataclass(frozen=True, slots=True)
class Auth:
    ig_user_id: str
    access_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Published:
    external_post_id: str
    url: str
    published_at: datetime


class Instagram(Protocol):
    async def publish_reel(
        self, auth: Auth, *, video_url: str, caption: str, cover_url: str | None, before_publish: BeforePublish
    ) -> Published: ...

    async def reconcile(
        self, auth: Auth, external_post_id: str, caption: str | None = None, since: datetime | None = None
    ) -> dict[str, Any] | None:
        """None: still unknown. {"status": published|published_unverified|not_published, ...}."""
        ...


class GraphClient:
    def __init__(
        self,
        *,
        graph_base: str = DEFAULT_GRAPH_BASE,
        api_version: str = DEFAULT_API_VERSION,
        timeout_s: float = 60.0,
        poll_interval_s: float = 2.0,
        poll_max_attempts: int = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base, self._version = graph_base.rstrip("/"), api_version.lstrip("/")
        self._timeout, self._poll, self._poll_max, self._client = timeout_s, poll_interval_s, poll_max_attempts, client

    def __repr__(self) -> str:
        return f"GraphClient(graph_base={self._base!r}, api_version={self._version!r}, token=***)"

    async def publish_reel(
        self, auth: Auth, *, video_url: str, caption: str, cover_url: str | None, before_publish: BeforePublish
    ) -> Published:
        if not video_url.startswith("https://"):
            raise InstagramAPIError(
                ClassifiedError("instagram_invalid_request", False, "video_url must be public https")
            )
        body: dict[str, Any] = {
            "media_type": "REELS", "caption": caption, "video_url": video_url, "access_token": auth.access_token,
        }  # fmt: skip
        if cover_url and cover_url.startswith("https://"):
            body["cover_url"] = cover_url
        created = await self._request("POST", f"{auth.ig_user_id}/media", data=body)
        container = created.get("id")
        if not container:
            raise InstagramAPIError(ClassifiedError("instagram_no_container", False, "missing container id"))
        container = str(container)
        try:
            await self._wait_finished(auth, container)
            await before_publish(container)  # arm the ledger, ask for confirmation; may raise to abort
            media_id = await self._media_publish(auth, container)
        except UnknownOutcomeError as exc:
            raise UnknownOutcomeError(str(exc), external_post_id=container) from exc
        permalink = await self._permalink(auth, media_id)
        return Published(media_id, permalink or f"https://www.instagram.com/reel/{media_id}/", datetime.now(UTC))

    async def reconcile(
        self, auth: Auth, external_post_id: str, caption: str | None = None, since: datetime | None = None
    ) -> dict[str, Any] | None:
        media = await self._get_media(auth, external_post_id)
        if media and media.get("permalink"):
            return _published(str(media.get("id") or external_post_id), media["permalink"], media.get("timestamp"))
        try:
            status = await self._status(auth, external_post_id)
        except InstagramAPIError:
            return None
        if status in {"ERROR", "EXPIRED"}:
            return {"status": "not_published", "container_status": status}
        if status != "PUBLISHED":
            return None
        # Published: match among the latest posts by caption and time, never "the newest one".
        floor = (since - timedelta(minutes=5)) if since is not None else None
        for m in await self._recent_media(auth):
            if caption is not None and (m.get("caption") or "").strip() != caption.strip():
                continue
            ts = _parse_ts(m.get("timestamp"))
            if floor is not None and ts is not None and ts < floor:
                continue
            return _published(str(m.get("id")), m.get("permalink"), m.get("timestamp"))
        return {"status": "published_unverified", "container_id": external_post_id}

    async def _wait_finished(self, auth: Auth, container: str) -> None:
        for _ in range(self._poll_max):
            status = await self._status(auth, container)
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramAPIError(ClassifiedError("instagram_container_failed", False, f"container {status}"))
            await asyncio.sleep(self._poll)
        raise UnknownOutcomeError("container status poll timed out", external_post_id=container)

    async def _status(self, auth: Auth, container: str) -> str | None:
        data = await self._get(container, auth, {"fields": "status_code"})
        code = data.get("status_code")
        return None if code is None else str(code)

    async def _media_publish(self, auth: Auth, container: str) -> str:
        try:
            data = await self._request(
                "POST", f"{auth.ig_user_id}/media_publish",
                data={"creation_id": container, "access_token": auth.access_token}, retry_ambiguous=False,
            )  # fmt: skip
        except InstagramAPIError as exc:
            if exc.classified.code in {"instagram_transport", "instagram_5xx", "instagram_bad_body"}:
                raise UnknownOutcomeError(
                    f"media_publish outcome unknown ({exc.classified.code})", external_post_id=container
                ) from exc
            raise
        if not data.get("id"):
            raise UnknownOutcomeError("media_publish returned no id", external_post_id=container)
        return str(data["id"])

    async def _permalink(self, auth: Auth, media_id: str) -> str | None:
        data = await self._get_media(auth, media_id)
        link = (data or {}).get("permalink")
        return link if isinstance(link, str) else None

    async def _get_media(self, auth: Auth, media_id: str) -> dict[str, Any] | None:
        try:
            return await self._get(media_id, auth, {"fields": "id,permalink,timestamp,media_type"})
        except InstagramAPIError:
            return None

    async def _recent_media(self, auth: Auth, limit: int = 10) -> list[dict[str, Any]]:
        try:
            data = await self._get(
                f"{auth.ig_user_id}/media", auth, {"fields": "id,permalink,timestamp,caption", "limit": str(limit)}
            )
        except InstagramAPIError:
            return []
        items = data.get("data")
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    async def _get(self, path: str, auth: Auth, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request("GET", path, params={**params, "access_token": auth.access_token})

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        retry_ambiguous: bool = True,
    ) -> dict[str, Any]:
        """`retry_ambiguous=False`: a transport error or 5xx raises at once (it may have taken effect)."""
        url = f"{self._base}/{self._version}/{path.lstrip('/')}"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns = self._client is None
        try:
            delay = 0.5
            for attempt in range(5):
                try:
                    resp = (
                        await client.get(url, params=params) if method == "GET" else await client.post(url, data=data)
                    )
                except httpx.HTTPError as exc:
                    log.warning("instagram_transport_error attempt=%s", attempt + 1)
                    if attempt == 4 or not retry_ambiguous:
                        raise InstagramAPIError(ClassifiedError("instagram_transport", True, str(exc))) from exc
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                body = _json(resp)
                api = body if isinstance(body, dict) else None
                err_code = ((api or {}).get("error") or {}).get("code") if api else None
                if resp.status_code == 429 or err_code in {4, 17, 32, 613}:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60.0)
                    continue
                if resp.status_code >= 500:
                    if not retry_ambiguous:
                        raise InstagramAPIError(
                            ClassifiedError("instagram_5xx", True, f"HTTP {resp.status_code}"),
                            status_code=resp.status_code,
                        )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                if resp.status_code >= 400 or (api is not None and api.get("error") is not None):
                    log.warning("instagram_graph_error path=%s status=%s", path, resp.status_code)
                    raise InstagramAPIError(
                        classify_graph_error(status_code=resp.status_code, body=api), status_code=resp.status_code
                    )
                if api is None:
                    raise InstagramAPIError(ClassifiedError("instagram_bad_body", True, "non-json response"))
                return api
            raise InstagramAPIError(ClassifiedError("instagram_retries_exhausted", True, "retries"))
        finally:
            if owns:
                await client.aclose()


def _published(media_id: str, permalink: str | None, ts: Any) -> dict[str, Any]:
    return {
        "status": "published", "external_post_id": media_id,
        "url": permalink or f"https://www.instagram.com/reel/{media_id}/",
        "published_at": ts or datetime.now(UTC).isoformat(),
    }  # fmt: skip


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        if len(raw) > 5 and raw[-5] in "+-" and raw[-3] != ":":  # 2026-11-10T10:00:00+0000
            raw = raw[:-2] + ":" + raw[-2:]
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
