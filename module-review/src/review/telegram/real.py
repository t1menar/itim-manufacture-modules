"""Real Telegram Bot API client (long-poll getUpdates + outbound methods).

Never logs the bot token. Tests must mock HTTP — this module does not contact
api.telegram.org unless REVIEW_TELEGRAM_MODE=real and a token is configured.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from review.observability.logging import get_logger
from review.telegram.updates import TelegramUpdate

log = get_logger(__name__)

BOT_API_UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024  # Bot API multipart upload limit
BOT_API_URL_FETCH_LIMIT_BYTES = 20 * 1024 * 1024  # Telegram fetches URLs up to ~20 MB


class TelegramAPIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
        retry_after: float | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after
        self.description = description


class RealTelegramBot:
    """httpx-backed Telegram Bot API. Token is never included in repr/logs."""

    def __init__(
        self,
        token: str,
        *,
        api_base: str = "https://api.telegram.org",
        timeout_s: float = 60.0,
        max_retries: int = 5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("telegram bot token is required for real mode")
        self._token = token.strip()
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._client = client
        self._owns_client = client is None

    def __repr__(self) -> str:
        return f"RealTelegramBot(api_base={self._api_base!r}, token=***)"

    def _url(self, method: str) -> str:
        # Token sits in the path per Bot API; never log this URL.
        return f"{self._api_base}/bot{self._token}/{method}"

    async def _client_ctx(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        *,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        delay = 0.5
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            client = await self._client_ctx()
            owns = self._client is None
            try:
                if files:
                    resp = await client.post(self._url(method), data=data or {}, files=files)
                elif data is not None:
                    resp = await client.post(self._url(method), json=data)
                else:
                    resp = await client.get(self._url(method), params=params or {})
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("telegram_http_error", method=method, attempt=attempt + 1)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            finally:
                if owns:
                    await client.aclose()

            if resp.status_code == 429:
                retry_after = _retry_after(resp)
                log.warning("telegram_rate_limited", method=method, retry_after=retry_after)
                await asyncio.sleep(retry_after or delay)
                delay = min(delay * 2, 60.0)
                continue
            if resp.status_code >= 500:
                log.warning("telegram_5xx", method=method, status=resp.status_code, attempt=attempt + 1)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if resp.status_code >= 400:
                payload = _safe_json(resp)
                desc = None
                code = None
                if isinstance(payload, dict):
                    desc = str(payload.get("description") or "") or None
                    code = payload.get("error_code")
                    if isinstance(code, int) is False:
                        code = None
                raise TelegramAPIError(
                    f"telegram {method} HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    error_code=code,
                    description=desc,
                )
            payload = _safe_json(resp)
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise TelegramAPIError(
                    f"telegram {method} unexpected body",
                    status_code=resp.status_code,
                    description=str(payload)[:200] if payload else None,
                )
            result = payload.get("result")
            return result if isinstance(result, dict) else {"result": result}
        raise TelegramAPIError(f"telegram {method} exhausted retries: {last_exc}")

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        long_poll_s: int = 25,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": long_poll_s,
            "limit": limit,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        if offset is not None:
            params["offset"] = offset
        # Long-poll needs a longer client timeout than the Bot API timeout.
        client = self._client or httpx.AsyncClient(timeout=max(self._timeout, float(long_poll_s) + 10.0))
        owns = self._client is None
        try:
            delay = 0.5
            for attempt in range(self._max_retries):
                try:
                    resp = await client.get(self._url("getUpdates"), params=params)
                except httpx.HTTPError:
                    log.warning("telegram_getUpdates_transport", attempt=attempt + 1)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                if resp.status_code == 429:
                    await asyncio.sleep(_retry_after(resp) or delay)
                    continue
                if resp.status_code >= 500:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                if resp.status_code >= 400:
                    raise TelegramAPIError(
                        f"getUpdates HTTP {resp.status_code}",
                        status_code=resp.status_code,
                    )
                payload = _safe_json(resp)
                if not isinstance(payload, dict) or not payload.get("ok"):
                    raise TelegramAPIError("getUpdates bad body")
                result = payload.get("result") or []
                return [u for u in result if isinstance(u, dict)]
            raise TelegramAPIError("getUpdates exhausted retries")
        finally:
            if owns:
                await client.aclose()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
            body["allow_sending_without_reply"] = allow_sending_without_reply
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        result = await self._request("sendMessage", data=body)
        return {"message_id": int(result["message_id"]), "chat_id": chat_id, "text": text}

    async def send_video(
        self,
        chat_id: int,
        video: str,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        allow_sending_without_reply: bool = False,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        size = await _probe_size(video)
        if size is not None and size > BOT_API_UPLOAD_LIMIT_BYTES:
            log.warning("telegram_video_too_large", size=size, limit=BOT_API_UPLOAD_LIMIT_BYTES)
            text = (
                "Видео слишком большое для Telegram Bot API "
                f"(>{BOT_API_UPLOAD_LIMIT_BYTES // (1024 * 1024)} MB). Ссылка:\n{video}"
            )
            if caption:
                text = f"{caption}\n\n{text}"
            return await self.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=allow_sending_without_reply,
                reply_markup=reply_markup,
            )
        body: dict[str, Any] = {"chat_id": chat_id, "video": video, "supports_streaming": True}
        if caption:
            body["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
            body["allow_sending_without_reply"] = allow_sending_without_reply
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        try:
            result = await self._request("sendVideo", data=body)
        except TelegramAPIError as exc:
            # URL fetch limit ~20 MB or other send failures → fall back to a link message.
            desc = (exc.description or "").lower()
            if (
                "too big" in desc
                or "file is too big" in desc
                or (size and size > BOT_API_URL_FETCH_LIMIT_BYTES)
            ):
                log.warning("telegram_video_fallback_link", description=exc.description)
                text = f"{caption + chr(10) + chr(10) if caption else ''}Видео (ссылка):\n{video}"
                return await self.send_message(
                    chat_id,
                    text,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=allow_sending_without_reply,
                    reply_markup=reply_markup,
                )
            raise
        return {
            "message_id": int(result["message_id"]),
            "chat_id": chat_id,
            "video": video,
            "caption": caption,
        }

    async def edit_message_reply_markup(
        self, chat_id: int, message_id: int, reply_markup: dict[str, Any] | None = None
    ) -> None:
        body: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        else:
            body["reply_markup"] = {"inline_keyboard": []}
        await self._request("editMessageReplyMarkup", data=body)

    async def answer_callback_query(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        body: dict[str, Any] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            body["text"] = text[:200]
        await self._request("answerCallbackQuery", data=body)


def parse_update(raw: dict[str, Any]) -> TelegramUpdate | None:
    """Map a Bot API Update object to TelegramUpdate."""
    update_id = raw.get("update_id")
    if not isinstance(update_id, int):
        return None
    if "callback_query" in raw and isinstance(raw["callback_query"], dict):
        cq = raw["callback_query"]
        msg = cq.get("message") if isinstance(cq.get("message"), dict) else {}
        chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
        from_user = cq.get("from") if isinstance(cq.get("from"), dict) else {}
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        if not isinstance(chat_id, int) or not isinstance(user_id, int):
            return None
        return TelegramUpdate(
            update_id=update_id,
            chat_id=chat_id,
            user_id=user_id,
            callback_data=str(cq["data"]) if cq.get("data") is not None else None,
            callback_message_id=int(msg["message_id"]) if msg.get("message_id") is not None else None,
            callback_query_id=str(cq["id"]) if cq.get("id") is not None else None,
        )
    if "message" in raw and isinstance(raw["message"], dict):
        msg = raw["message"]
        chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
        from_user = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        if not isinstance(chat_id, int) or not isinstance(user_id, int):
            return None
        reply = msg.get("reply_to_message") if isinstance(msg.get("reply_to_message"), dict) else None
        reply_id = int(reply["message_id"]) if reply and reply.get("message_id") is not None else None
        text = msg.get("text")
        return TelegramUpdate(
            update_id=update_id,
            chat_id=chat_id,
            user_id=user_id,
            text=str(text) if text is not None else None,
            reply_to_message_id=reply_id,
        )
    return None


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        params = payload.get("parameters")
        if isinstance(params, dict) and params.get("retry_after") is not None:
            try:
                return float(params["retry_after"])
            except (TypeError, ValueError):
                pass
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            return None
    return None


async def _probe_size(video: str) -> int | None:
    """Best-effort Content-Length for http(s) URLs; None if unknown."""
    if not video.startswith(("http://", "https://")):
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.head(video, follow_redirects=True)
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                return int(cl)
    except httpx.HTTPError:
        return None
    return None
