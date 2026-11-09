"""Build review card caption and inline keyboard."""

from __future__ import annotations

from typing import Any


def approve_reject_keyboard(run_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Одобрить", "callback_data": f"approve:{run_id}"},
                {"text": "Отклонить", "callback_data": f"reject:{run_id}"},
            ]
        ]
    }


def stale_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "устарело", "callback_data": "noop"}]]}


def card_caption(*, title: str, description: str, version: int, language: str = "en") -> str:
    title = title.strip() or "(без заголовка)"
    desc = description.strip()
    lines = [f"v{version} · {language}", title]
    if desc:
        lines.append(desc[:500])
    return "\n".join(lines)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_meta(job_input: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return title, description, video_ref, language from job input/upstream.

    D21: idea body is not in the job; only opaque idea_ref. Caption text comes from
    content_revision metadata. Language prefers channels[0].language, else "en".
    """
    _ = _as_dict(job_input.get("idea_ref"))  # present for contract; unused for caption
    upstream = _as_dict(job_input.get("upstream"))
    rev = _as_dict(upstream.get("content_revision"))
    meta = _as_dict(rev.get("metadata"))
    title = str(meta.get("title") or "")
    description = str(meta.get("description") or "")
    video = _as_dict(rev.get("video"))
    video_ref = str(video.get("ref") or upstream.get("video_ref") or "s3://manufacture/fake/review.mp4")
    language = "en"
    channels = job_input.get("channels")
    if isinstance(channels, list) and channels:
        ch0 = channels[0]
        if isinstance(ch0, dict) and ch0.get("language"):
            language = str(ch0["language"])
    return title, description, video_ref, language
