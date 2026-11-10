"""Classify Instagram Graph API errors for retry vs permanent failure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    code: str
    retryable: bool
    message: str


def classify_graph_error(
    *, status_code: int | None, body: dict[str, Any] | None, fallback_message: str = "instagram_error"
) -> ClassifiedError:
    err = (body or {}).get("error") if isinstance(body, dict) else None
    err = err if isinstance(err, dict) else {}
    api_code, subcode = err.get("code"), err.get("error_subcode")
    message = str(err.get("message") or fallback_message)
    # Rate and publishing quota: code 9 / subcode 2207042 are common.
    if status_code == 429 or api_code in {4, 9, 17, 32, 613} or subcode in {2207042, 2207003}:
        return ClassifiedError("instagram_rate_limit", True, message)
    if status_code is not None and status_code >= 500:
        return ClassifiedError("instagram_5xx", True, message)
    if api_code in {190, 102, 10} or status_code in {401, 403}:
        return ClassifiedError("instagram_auth", False, message)  # permanent until the token is fixed
    if api_code in {100, 200} or "video_url" in message.lower() or "media_type" in message.lower():
        return ClassifiedError("instagram_invalid_request", False, message)
    if status_code is not None and 400 <= status_code < 500:
        return ClassifiedError("instagram_client_error", False, message)
    return ClassifiedError("instagram_error", True, message)


class InstagramAPIError(Exception):
    def __init__(self, classified: ClassifiedError, *, status_code: int | None = None) -> None:
        super().__init__(classified.message)
        self.classified, self.status_code = classified, status_code


class UnknownOutcomeError(Exception):
    """Publish may or may not have succeeded: the caller reconciles and never resends blindly."""

    def __init__(self, message: str, *, external_post_id: str | None = None) -> None:
        super().__init__(message)
        self.external_post_id = external_post_id


class PublishCancelled(Exception):
    """`confirm` said no (rejected, superseded or past its deadline): the container is abandoned."""
