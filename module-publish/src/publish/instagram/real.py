"""Real Instagram Graph API Reels publisher.

Never logs access tokens. Tests must mock the Graph host — this client does not
call graph.facebook.com / graph.instagram.com unless PUBLISH_INSTAGRAM_MODE=real.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from publish.instagram.base import PublishResult, UnknownOutcomeError
from publish.instagram.errors import ClassifiedError, classify_graph_error
from publish.observability.logging import get_logger

log = get_logger(__name__)

# Official content publishing docs (Meta): Reels via media_type=REELS + public video_url,
# poll container status_code until FINISHED, then media_publish. Rolling publish quota via
# content_publishing_limit (do not hardcode; read quota_total). Graph version configurable;
# default v22.0 matches Meta IG User Media reference examples.
DEFAULT_API_VERSION = "v22.0"
DEFAULT_GRAPH_BASE = "https://graph.instagram.com"
DEFAULT_UPLOAD_BASE = "https://rupload.facebook.com"  # resumable upload host (Meta docs)


@dataclass(frozen=True, slots=True)
class AccountAuth:
    ig_user_id: str
    access_token: str = field(repr=False)


AccountResolver = Callable[[str], Awaitable[AccountAuth]]


class InstagramAPIError(Exception):
    def __init__(self, classified: ClassifiedError, *, status_code: int | None = None) -> None:
        super().__init__(classified.message)
        self.classified = classified
        self.status_code = status_code


class RealInstagramClient:
    """Graph API Reels publisher (create container → poll → media_publish → permalink)."""

    dry_run: bool = False

    def __init__(
        self,
        *,
        resolve_account: AccountResolver,
        graph_base: str = DEFAULT_GRAPH_BASE,
        api_version: str = DEFAULT_API_VERSION,
        timeout_s: float = 60.0,
        poll_interval_s: float = 2.0,
        poll_max_attempts: int = 60,
        client: httpx.AsyncClient | None = None,
        video_url_resolver: Callable[[str], Awaitable[str]] | None = None,
        video_loader: Callable[[str], Awaitable[bytes]] | None = None,
        upload_base: str = DEFAULT_UPLOAD_BASE,
    ) -> None:
        self._resolve = resolve_account
        self._base = graph_base.rstrip("/")
        self._version = api_version.lstrip("/")
        self._timeout = timeout_s
        self._poll_interval = poll_interval_s
        self._poll_max = poll_max_attempts
        self._client = client
        self._video_url_resolver = video_url_resolver
        # With a loader an s3:// video is uploaded as a file (resumable upload): no public URL needed.
        self._video_loader = video_loader
        self._upload_base = upload_base.rstrip("/")
        # Last container id per account for reconcile after unknown.
        self._last_container: dict[str, str] = {}

    def __repr__(self) -> str:
        return f"RealInstagramClient(graph_base={self._base!r}, api_version={self._version!r}, token=***)"

    def _url(self, path: str) -> str:
        return f"{self._base}/{self._version}/{path.lstrip('/')}"

    async def publish_reel(
        self,
        *,
        account_id: str,
        video_ref: str,
        caption: str,
        cover_ref: str | None = None,
        intent_id: str | None = None,
    ) -> PublishResult:
        _ = intent_id
        video_bytes: bytes | None = None
        video_url: str | None = None
        if self._video_loader is not None and video_ref.startswith("s3://"):
            video_bytes = await self._video_loader(video_ref)
        elif self._video_url_resolver is not None and video_ref.startswith("s3://"):
            video_url = await self._video_url_resolver(video_ref)
        else:
            video_url = _require_public_https_url(video_ref)
        auth = await self._resolve(account_id)
        # Optional quota peek (non-fatal if missing permissions).
        try:
            await self.content_publishing_limit(auth)
        except InstagramAPIError as exc:
            if not exc.classified.retryable and exc.classified.code == "instagram_auth":
                raise
            log.warning("content_publishing_limit_skipped", code=exc.classified.code)

        container_id = await self._create_reels_container(
            auth, video_url=video_url, caption=caption, cover_url=cover_ref
        )
        self._last_container[account_id] = container_id
        try:
            if video_bytes is not None:
                await self._upload_video(auth, container_id, video_bytes)
            await self._wait_container_finished(auth, container_id)
            media_id = await self._media_publish(auth, container_id)
        except Exception as exc:
            # Ambiguous after create/publish call → unknown (reconcile, never blind resend).
            if isinstance(exc, InstagramAPIError) and not exc.classified.retryable:
                raise RuntimeError(exc.classified.message) from exc
            raise UnknownOutcomeError(
                f"publish outcome unknown after container {container_id}",
                account_id=account_id,
                external_post_id=container_id,
            ) from exc

        permalink = await self._permalink(auth, media_id)
        return PublishResult(
            external_post_id=media_id,
            url=permalink or f"https://www.instagram.com/reel/{media_id}/",
            published_at=datetime.now(UTC),
        )

    async def reconcile(self, *, account_id: str, external_post_id: str) -> dict[str, Any] | None:
        """Find an already-published media by container id or media id (no duplicate publish)."""
        auth = await self._resolve(account_id)
        # Try as media id first.
        media = await self._get_media(auth, external_post_id)
        if media and media.get("permalink"):
            return {
                "account_id": account_id,
                "external_post_id": str(media.get("id") or external_post_id),
                "url": media["permalink"],
                "published_at": media.get("timestamp") or datetime.now(UTC).isoformat(),
            }
        # Container may already be PUBLISHED — check status.
        status = await self._container_status(auth, external_post_id)
        if status == "PUBLISHED":
            # Look up recent media (best-effort; avoid creating a new container).
            recent = await self._recent_media(auth, limit=5)
            if recent:
                m = recent[0]
                return {
                    "account_id": account_id,
                    "external_post_id": str(m.get("id")),
                    "url": m.get("permalink") or f"https://www.instagram.com/reel/{m.get('id')}/",
                    "published_at": m.get("timestamp") or datetime.now(UTC).isoformat(),
                }
        return None

    async def content_publishing_limit(self, auth: AccountAuth) -> dict[str, Any]:
        data = await self._get(
            f"{auth.ig_user_id}/content_publishing_limit",
            auth,
            params={"fields": "quota_usage,config"},
        )
        return data

    async def _create_reels_container(
        self,
        auth: AccountAuth,
        *,
        video_url: str | None,
        caption: str,
        cover_url: str | None,
    ) -> str:
        body: dict[str, Any] = {
            "media_type": "REELS",
            "caption": caption,
            "access_token": auth.access_token,
        }
        if video_url is not None:
            body["video_url"] = video_url
        else:
            body["upload_type"] = "resumable"  # the file follows to the upload host
        if cover_url and cover_url.startswith("https://"):
            body["cover_url"] = cover_url
        data = await self._post(f"{auth.ig_user_id}/media", auth, data=body)
        cid = data.get("id")
        if not cid:
            raise InstagramAPIError(
                ClassifiedError("instagram_no_container", False, "missing container id"),
                status_code=200,
            )
        return str(cid)

    async def _upload_video(self, auth: AccountAuth, container_id: str, data: bytes) -> None:
        """Send the file to the container (Meta resumable upload). Safe to repeat: offset 0 restarts it."""
        url = f"{self._upload_base}/ig-api-upload/{self._version}/{container_id}"
        headers = {
            "Authorization": f"OAuth {auth.access_token}",
            "offset": "0",
            "file_size": str(len(data)),
            "Content-Type": "application/octet-stream",
        }
        client = self._client or httpx.AsyncClient(timeout=max(self._timeout, 300.0))
        owns = self._client is None
        try:
            delay = 1.0
            for attempt in range(3):
                try:
                    resp = await client.post(url, content=data, headers=headers)
                except httpx.HTTPError as exc:
                    log.warning("instagram_upload_transport_error", attempt=attempt + 1)
                    if attempt == 2:
                        raise InstagramAPIError(
                            ClassifiedError("instagram_upload_transport", True, str(exc))
                        ) from exc
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                body = _json(resp)
                if resp.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if resp.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
                    classified = classify_graph_error(
                        status_code=resp.status_code, body=body if isinstance(body, dict) else None
                    )
                    raise InstagramAPIError(classified, status_code=resp.status_code)
                return
        finally:
            if owns:
                await client.aclose()

    async def _wait_container_finished(self, auth: AccountAuth, container_id: str) -> None:
        for _ in range(self._poll_max):
            status = await self._container_status(auth, container_id)
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramAPIError(
                    ClassifiedError("instagram_container_failed", False, f"container {status}"),
                )
            if status == "PUBLISHED":
                return
            await asyncio.sleep(self._poll_interval)
        raise UnknownOutcomeError(
            "container status poll timed out",
            account_id=auth.ig_user_id,
            external_post_id=container_id,
        )

    async def _container_status(self, auth: AccountAuth, container_id: str) -> str | None:
        data = await self._get(container_id, auth, params={"fields": "status_code"})
        code = data.get("status_code")
        if code is None:
            return None
        return str(code)

    async def _media_publish(self, auth: AccountAuth, container_id: str) -> str:
        data = await self._post(
            f"{auth.ig_user_id}/media_publish",
            auth,
            data={"creation_id": container_id, "access_token": auth.access_token},
        )
        mid = data.get("id")
        if not mid:
            raise UnknownOutcomeError(
                "media_publish returned no id",
                account_id=auth.ig_user_id,
                external_post_id=container_id,
            )
        return str(mid)

    async def _permalink(self, auth: AccountAuth, media_id: str) -> str | None:
        data = await self._get_media(auth, media_id)
        if not data:
            return None
        permalink = data.get("permalink")
        return permalink if isinstance(permalink, str) else None

    async def _get_media(self, auth: AccountAuth, media_id: str) -> dict[str, Any] | None:
        try:
            return await self._get(media_id, auth, params={"fields": "id,permalink,timestamp,media_type"})
        except InstagramAPIError:
            return None

    async def _recent_media(self, auth: AccountAuth, *, limit: int = 5) -> list[dict[str, Any]]:
        try:
            data = await self._get(
                f"{auth.ig_user_id}/media",
                auth,
                params={"fields": "id,permalink,timestamp", "limit": str(limit)},
            )
        except InstagramAPIError:
            return []
        items = data.get("data")
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    async def _get(
        self, path: str, auth: AccountAuth, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        q = dict(params or {})
        q["access_token"] = auth.access_token
        return await self._request("GET", path, params=q)

    async def _post(self, path: str, auth: AccountAuth, *, data: dict[str, Any]) -> dict[str, Any]:
        _ = auth
        return await self._request("POST", path, data=data)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        # Strip token from logs — never include params/data in log events.
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns = self._client is None
        try:
            delay = 0.5
            for attempt in range(5):
                try:
                    if method == "GET":
                        resp = await client.get(url, params=params)
                    else:
                        resp = await client.post(url, data=data)
                except httpx.HTTPError as exc:
                    log.warning("instagram_transport_error", attempt=attempt + 1)
                    if attempt == 4:
                        raise InstagramAPIError(
                            ClassifiedError("instagram_transport", True, str(exc))
                        ) from exc
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                body = _json(resp)
                if resp.status_code == 429 or (
                    isinstance(body, dict)
                    and isinstance(body.get("error"), dict)
                    and body["error"].get("code") in {4, 17, 32, 613}
                ):
                    classified = classify_graph_error(
                        status_code=resp.status_code, body=body if isinstance(body, dict) else None
                    )
                    await asyncio.sleep(classified.retry_after_s or delay)
                    delay = min(delay * 2, 60.0)
                    continue
                if resp.status_code >= 500:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                if resp.status_code >= 400 or (isinstance(body, dict) and body.get("error") is not None):
                    classified = classify_graph_error(
                        status_code=resp.status_code, body=body if isinstance(body, dict) else None
                    )
                    raise InstagramAPIError(classified, status_code=resp.status_code)
                if not isinstance(body, dict):
                    raise InstagramAPIError(
                        ClassifiedError("instagram_bad_body", True, "non-json response"),
                        status_code=resp.status_code,
                    )
                return body
            raise InstagramAPIError(ClassifiedError("instagram_retries_exhausted", True, "retries"))
        finally:
            if owns:
                await client.aclose()


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _require_public_https_url(video_ref: str) -> str:
    """Graph API downloads video_url itself — must be a public https URL.

    s3:// and other private refs are not supported until MinIO (or equivalent) issues
    a time-limited presigned HTTPS URL for Meta to fetch.
    """
    if video_ref.startswith("https://"):
        return video_ref
    if video_ref.startswith("http://"):
        raise RuntimeError("instagram requires https video_url (http not accepted); got http:// ref")
    if video_ref.startswith("s3://"):
        raise RuntimeError(
            "instagram requires a public https video_url; configure MinIO "
            "(module_secrets s3.access_key/s3.secret_key + module_settings s3) "
            "so s3:// refs can be presigned"
        )
    raise RuntimeError(f"unsupported video_ref for Instagram publish: {video_ref!r}")
