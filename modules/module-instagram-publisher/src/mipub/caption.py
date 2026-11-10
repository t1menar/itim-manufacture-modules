"""Caption rules of Instagram: body limit, hashtag limit."""

from __future__ import annotations

CAPTION_BODY_MAX = 500
HASHTAGS_MAX = 8


def shorten_caption(caption: str, limit: int = CAPTION_BODY_MAX) -> str:
    """Keep the hook and the source line, and as many whole summary lines as fit in `limit`."""
    if len(caption) <= limit:
        return caption
    parts = [p for p in caption.strip().split("\n\n") if p.strip()]
    if len(parts) < 2:
        return caption[: limit - 1].rstrip() + "…"
    head = parts[0]
    tail = parts[-1] if parts[-1].lstrip().lower().startswith(("source", "src")) else ""
    middle = [ln for part in parts[1 : -1 if tail else None] for ln in part.split("\n") if ln.strip()]
    budget = limit - len(head) - len(tail) - 4
    kept: list[str] = []
    used = 0
    for ln in middle:
        if used + len(ln) + 1 > budget:
            break
        kept.append(ln)
        used += len(ln) + 1
    pieces = [head, *(["\n".join(kept)] if kept else []), *([tail] if tail else [])]
    out = "\n\n".join(pieces)
    return out if len(out) <= limit + 80 else head[: limit - 1].rstrip() + "…"


def compose_caption(
    caption: str, hashtags: list[str], *, body_max: int = CAPTION_BODY_MAX, tags_max: int = HASHTAGS_MAX
) -> str:
    body = shorten_caption(caption, body_max)
    tags = " ".join("#" + t.lstrip("#") for t in hashtags[:tags_max])
    return (body + "\n\n" + tags).strip() if tags else body
