"""What the owner sees: the card text and buttons for each gate. Pure functions, no I/O."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

APPROVE, REJECT = "ok", "no"
TEXT_MAX = 3800  # Telegram limit is 4096 for messages, 1024 for captions: long cards go as video + message


@dataclass(frozen=True, slots=True)
class Card:
    text: str
    video: str | None  # store uri of the video to attach (gate `post`)
    cover: str | None
    buttons: list[tuple[str, str]]  # (label, callback data)


def callback_data(session_id: int, action: str) -> str:
    return f"r:{session_id}:{action}"


def parse_callback(data: str) -> tuple[int, str] | None:
    parts = data.split(":")
    if len(parts) == 3 and parts[0] == "r" and parts[1].isdigit() and parts[2] in {APPROVE, REJECT}:
        return int(parts[1]), parts[2]
    return None


def _e(x: Any) -> str:
    return html.escape(str(x))


def script_card(p: dict[str, Any], round_: int, session_id: int) -> Card:
    """Gate 1: the script as text. `p`: {title, hook, takeaway, scenes[{id,title,narration}], post, cost_usd}."""
    lines = [f"<b>Script review</b>{_round(round_)}", f"<b>{_e(p.get('title', ''))}</b>"]
    if p.get("hook"):
        lines.append(f"Hook: {_e(p['hook'])}")
    if p.get("takeaway"):
        lines.append(f"Takeaway: {_e(p['takeaway'])}")
    for i, sc in enumerate(p.get("scenes", []), start=1):
        lines.append(f"{i}. <b>{_e(sc.get('title') or sc.get('id'))}</b>: {_e(sc.get('narration', ''))}".strip())
    post = p.get("post") or {}
    if post:
        lines.append(f"\nCaption: {_e(post.get('summary', ''))}")
    lines.append(_footer(p))
    return Card(_clip("\n".join(x for x in lines if x)), None, None, _buttons(session_id))


def post_card(p: dict[str, Any], round_: int, session_id: int) -> Card:
    """Gate 2: the finished post. `p`: {title, video{ref,duration_s,size}, cover, post{caption,hashtags}, account}."""
    video = p.get("video") or {}
    post = p.get("post") or {}
    head = f"<b>Post review</b>{_round(round_)}\n<b>{_e(p.get('title', ''))}</b>"
    meta = []
    if video.get("duration_s"):
        meta.append(f"{float(video['duration_s']):.0f} s")
    if video.get("size"):
        meta.append(f"{int(video['size']) / 1e6:.1f} MB")
    if p.get("account"):
        meta.append(f"account {_e(p['account'])}")
    body = [
        head,
        " · ".join(meta),
        "",
        _e(post.get("caption", "")),
        " ".join("#" + _e(str(t).lstrip("#")) for t in post.get("hashtags", [])),
    ]
    body.append(_footer(p))
    return Card(
        _clip("\n".join(x for x in body if x is not None)), video.get("ref"), p.get("cover"), _buttons(session_id)
    )


def build_card(gate: str, payload: dict[str, Any], round_: int, session_id: int) -> Card:
    if gate == "script":
        return script_card(payload, round_, session_id)
    if gate == "post":
        return post_card(payload, round_, session_id)
    raise ValueError(f"unknown gate {gate!r}")


def _buttons(session_id: int) -> list[tuple[str, str]]:
    return [("✅ Approve", callback_data(session_id, APPROVE)), ("❌ Reject", callback_data(session_id, REJECT))]


def _round(round_: int) -> str:
    return f" (revision {round_ - 1})" if round_ > 1 else ""


def _footer(p: dict[str, Any]) -> str:
    return f"\nCost so far: ${float(p['cost_usd']):.2f}" if p.get("cost_usd") is not None else ""


def _clip(text: str) -> str:
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1] + "…"
