"""Post text: caption template, hashtags and the metadata of a result ."""

from __future__ import annotations

import re
from typing import Any

HASH_COMMIT = re.compile(r"\b[0-9a-f]{12,40}\b")
DEFAULT_TEMPLATE = "{hook}\n\n{summary}\n\nSource: {source}"


def source_label(repo_url: str, ref: str) -> str:
    """`<repo host/path> · <ref>`; never the commit."""
    return f"{re.sub(r'^https?://', '', repo_url).rstrip('/')} · {ref}"


def _fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if m.group(1) in values:
            return values[m.group(1)]
        unknown.append(m.group(1))
        return m.group(0)

    return re.sub(r"\{([a-z_][a-z0-9_]*)\}", sub, text), unknown


def render_post(
    post: dict[str, Any],
    capture_values: dict[str, str],
    *,
    template: str | None,
    channel_hashtags: list[str],
    source: str,
    max_caption_chars: int,
    max_hashtags: int,
) -> tuple[dict[str, Any], list[str]]:
    """Returns (`{caption, hashtags, hook, summary}`, problems). Hashtags start with `#`."""
    problems: list[str] = []
    hook, u1 = _fill(post["hook"], capture_values)
    summary, u2 = _fill(post["summary"], capture_values)
    caption, u3 = _fill(template or DEFAULT_TEMPLATE, {"hook": hook, "summary": summary, "source": source})
    for name in (*u1, *u2, *u3):
        problems.append(f"unknown placeholder {{{name}}}: not a capture value and not in the template")
    tags: list[str] = []
    for t in [*channel_hashtags, *("#" + x.lstrip("#") for x in post.get("topic_hashtags", []))]:
        tag = "#" + t.lstrip("#")
        if tag.lower() not in [x.lower() for x in tags]:
            tags.append(tag)
    if len(caption) > max_caption_chars:
        problems.append(f"caption has {len(caption)} characters, limit {max_caption_chars}")
    if len(tags) > max_hashtags:
        problems.append(f"{len(tags)} hashtags including the fixed ones, limit {max_hashtags}")
    if HASH_COMMIT.search(caption):
        problems.append("the caption contains a commit-like hash")
    return {"caption": caption, "hashtags": tags, "hook": hook, "summary": summary}, problems


def build_metadata(script: dict[str, Any], rendered: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    """`variants[].metadata` title, description, topics and the Instagram caption."""
    return {
        "title": script["meta"]["title"],
        "description": rendered["summary"],
        "topics": [t.lstrip("#") for t in post.get("topic_hashtags", [])],
        "platforms": {"instagram": {"caption": rendered["caption"], "hashtags": rendered["hashtags"]}},
    }
