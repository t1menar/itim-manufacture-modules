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


def extract_meta(job_input: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return title, description, video_ref, language from job input/upstream."""
    upstream = job_input.get("upstream") if isinstance(job_input.get("upstream"), dict) else {}
    rev = upstream.get("content_revision") if isinstance(upstream.get("content_revision"), dict) else {}
    meta = rev.get("metadata") if isinstance(rev.get("metadata"), dict) else {}
    title = str(meta.get("title") or "")
    description = str(meta.get("description") or "")
    video = rev.get("video") if isinstance(rev.get("video"), dict) else {}
    video_ref = str(video.get("ref") or upstream.get("video_ref") or "s3://manufacture/fake/review.mp4")
    language = "en"
    idea = job_input.get("idea") if isinstance(job_input.get("idea"), dict) else {}
    if idea.get("language"):
        language = str(idea["language"])
    return title, description, video_ref, language
