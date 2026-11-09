"""Classify Instagram Graph API errors for retry vs permanent failure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    code: str
    retryable: bool
    message: str
    retry_after_s: float | None = None


def classify_graph_error(
    *,
    status_code: int | None,
    body: dict[str, Any] | None,
    fallback_message: str = "instagram_error",
) -> ClassifiedError:
    err = (body or {}).get("error") if isinstance(body, dict) else None
    err = err if isinstance(err, dict) else {}
    api_code = err.get("code")
    subcode = err.get("error_subcode")
    message = str(err.get("message") or fallback_message)
    # Rate / publishing quota (content_publishing_limit): code 9 / subcode 2207042 common.
    if status_code == 429 or api_code in {4, 9, 17, 32, 613} or subcode in {2207042, 2207003}:
        return ClassifiedError(
            code="instagram_rate_limit",
            retryable=True,
            message=message,
            retry_after_s=_retry_after(err),
        )
    if status_code is not None and status_code >= 500:
        return ClassifiedError(code="instagram_5xx", retryable=True, message=message)
    # OAuth / permission / invalid token — permanent until fixed.
    if api_code in {190, 102, 10} or status_code in {401, 403}:
        return ClassifiedError(code="instagram_auth", retryable=False, message=message)
    if api_code in {100, 200} or "video_url" in message.lower() or "media_type" in message.lower():
        return ClassifiedError(code="instagram_invalid_request", retryable=False, message=message)
    if status_code is not None and 400 <= status_code < 500:
        return ClassifiedError(code="instagram_client_error", retryable=False, message=message)
    return ClassifiedError(code="instagram_error", retryable=True, message=message)


def _retry_after(err: dict[str, Any]) -> float | None:
    for key in ("error_user_msg", "fbtrace_id"):
        _ = err.get(key)
    # Meta rarely returns a numeric retry; callers may use content_publishing_limit window.
    return None
