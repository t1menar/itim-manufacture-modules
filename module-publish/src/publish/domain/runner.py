"""Build stage-publish-output from FakeInstagramClient (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from publish.instagram.fake import FakeInstagramClient


async def run_publish_intents(
    *,
    client: FakeInstagramClient,
    intents: list[dict[str, Any]],
    platform: str = "instagram",
    video_ref: str = "s3://manufacture/fake/video.mp4",
    caption: str = "",
) -> dict[str, Any]:
    """Return a stage-publish-output body matching core/schemas/stage-publish-output.json."""
    publications: list[dict[str, Any]] = []
    for raw in intents:
        intent_id = str(raw.get("intent_id") or raw.get("id") or "")
        account_id = str(raw.get("platform_account_id") or raw.get("account_id") or "")
        handle = raw.get("handle")
        if not account_id:
            publications.append(
                {
                    "platform": platform,
                    "platform_account_id": "00000000-0000-0000-0000-000000000000",
                    "status": "failed",
                    "error": "missing platform_account_id",
                    "error_detail": {"code": "invalid_intent", "retryable": False},
                    "intent_id": intent_id or None,
                }
            )
            continue
        try:
            result = await client.publish_reel(
                account_id=account_id,
                video_ref=video_ref,
                caption=caption,
                intent_id=intent_id or None,
            )
            publications.append(
                {
                    "platform": platform,
                    "platform_account_id": account_id,
                    "handle": handle,
                    "external_post_id": result.external_post_id,
                    "url": result.url,
                    "published_at": result.published_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "published",
                    "error": None,
                    "dry_run": client.dry_run,
                    "intent_id": intent_id or None,
                }
            )
        except Exception as exc:
            publications.append(
                {
                    "platform": platform,
                    "platform_account_id": account_id,
                    "handle": handle,
                    "status": "failed",
                    "error": str(exc),
                    "error_detail": {
                        "code": "instagram_publish_failed",
                        "retryable": True,
                        "message": str(exc),
                    },
                    "intent_id": intent_id or None,
                }
            )
    return {"publications": publications}


def result_callback_body(output: dict[str, Any], *, finished_at: datetime | None = None) -> dict[str, Any]:
    """Core POST .../result body for a successful fake publish."""
    at = finished_at or datetime.now(UTC)
    return {
        "output": output,
        "artifacts": [],
        "finished_at": at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def parse_intent_ids(job_request: dict[str, Any]) -> list[UUID]:
    intents = (job_request.get("input") or {}).get("intents") or []
    out: list[UUID] = []
    for item in intents:
        raw = item.get("intent_id") if isinstance(item, dict) else None
        if raw:
            out.append(UUID(str(raw)))
    return out
