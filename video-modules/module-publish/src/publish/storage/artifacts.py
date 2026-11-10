"""Content-revision artifact checks. Fake/default: structural only (no download)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    video_ref: str
    sha256: str | None
    cover_ref: str | None
    caption: str


class ArtifactError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def verify_content_revision(upstream: dict[str, Any] | None, intents: list[dict[str, Any]]) -> ArtifactInfo:
    """Resolve video/caption from upstream.content_revision (or upstream.video) and validate refs."""
    upstream = upstream or {}
    rev = upstream.get("content_revision") if isinstance(upstream.get("content_revision"), dict) else None
    video = None
    caption = ""
    cover = None
    sha = None
    if isinstance(rev, dict):
        video = rev.get("video") if isinstance(rev.get("video"), dict) else None
        meta = rev.get("metadata") if isinstance(rev.get("metadata"), dict) else {}
        platforms = meta.get("platforms") if isinstance(meta, dict) else {}
        ig = platforms.get("instagram") if isinstance(platforms, dict) else {}
        if isinstance(ig, dict):
            caption = str(ig.get("caption") or "")
            tags = ig.get("hashtags") or []
            if isinstance(tags, list) and tags:
                caption = (caption + " " + " ".join(str(t) for t in tags)).strip()
        cover = rev.get("cover") if isinstance(rev.get("cover"), str) else None
    if video is None and isinstance(upstream.get("video"), dict):
        video = upstream["video"]
    if not isinstance(video, dict) or not video.get("ref"):
        # Fall back: still allow fake publish with a synthetic ref when intents exist (MVP dry path).
        if intents:
            return ArtifactInfo(
                video_ref="s3://manufacture/fake/from-intent.mp4",
                sha256=None,
                cover_ref=None,
                caption=caption or "manufacture",
            )
        raise ArtifactError("artifact_missing", "content_revision.video.ref is required")
    ref = str(video["ref"])
    if not (ref.startswith("s3://") or ref.startswith("https://")):
        raise ArtifactError("artifact_invalid", f"unsupported video ref scheme: {ref!r}")
    sha = str(video["sha256"]) if video.get("sha256") else None
    return ArtifactInfo(video_ref=ref, sha256=sha, cover_ref=cover, caption=caption or "manufacture")
