"""Captions and glossary notes under the caption."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mvrender import timing as tm
from mvrender.draw.canvas import Canvas, parse_markup
from mvrender.layout import CAPTION_LH, CAPTION_MAX_W, CAPTION_X, CAPTION_Y, NOTE_Y, W
from mvrender.palette import mix
from mvrender.timing import NoteWindow


def ramp(t: float, start: float, dur: float = 0.35) -> float:
    x = max(0.0, min(1.0, (t - start) / dur))
    return 1 - (1 - x) ** 3


def caption_list(scene: dict[str, Any], st: tm.SceneTiming) -> list[tuple[float, list[str]]]:
    """(start time, lines) of every caption of the scene, including debugger step captions."""
    items: list[tuple[float, list[str]]] = []
    for cap in scene.get("captions", []):
        items.append((tm.anchor_time(cap.get("at"), st.marks), list(cap["lines"])))
    for step_t in st.steps:
        step = next(s for s in scene["debugger"]["steps"] if s["id"] == step_t.id)
        items.append((step_t.start, list(step["caption"])))
    return sorted(items, key=lambda it: it[0])


def draw_caption(cv: Canvas, scene: dict[str, Any], st: tm.SceneTiming, t: float, first_scene: bool) -> None:
    items = caption_list(scene, st)
    cur = items[0]
    for it in items:
        if it[0] <= t:
            cur = it
    c0, lines = cur
    ca = ramp(t, c0, 0.4)
    y = CAPTION_Y + 16 * (1 - ca)
    step_s = float((scene.get("hook") or {}).get("line_step_s", 1.2))
    for i, ln in enumerate(lines):
        delay = min(i, 2) * step_s if first_scene else i * 0.12
        la = ramp(t, c0 + delay, 0.4)
        plain = ln.replace("*", "")
        w = cv.width("caption", plain)
        size = None if w <= CAPTION_MAX_W else int(60 * CAPTION_MAX_W / w)
        px = size or 60
        cv.segments(
            CAPTION_X,
            y + (60 - px) * 0.6,
            parse_markup(ln, cv.pal.ink, cv.pal.accent_text),
            "caption",
            la,
            size=size,
        )
        y += CAPTION_LH


def wrap_words(cv: Canvas, text: str, role: str, max_w: float, first_w: float | None = None) -> list[str]:
    lines: list[str] = []
    cur = ""
    for w in text.split(" "):
        lim = first_w if (first_w and not lines) else max_w
        cand = f"{cur} {w}" if cur else w
        if cv.width(role, cand.replace("*", "")) <= lim or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_notes(cv: Canvas, windows: Sequence[NoteWindow], t: float, max_lines: int = 2) -> None:
    """Glossary chip: accent pill with the term and a short definition."""
    pal = cv.pal
    for w in windows:
        al = min(ramp(t, w.start, 0.3), 1 - ramp(t, w.end, 0.3))
        if al <= 0 or t < w.start - 0.05:
            continue
        x, y = 60.0, NOTE_Y + 6 * (1 - al)
        tw = cv.width("note_term", w.term) + 28
        cv.d.rounded_rectangle((x, y, x + tw, y + 36), radius=18, fill=mix(pal.accent, pal.page, al))
        cv.text(x + 14, y + 3, w.term, "note_term", mix((255, 255, 255), pal.accent, al))
        lines = wrap_words(cv, w.text, "note", W - 120, first_w=W - 60 - (x + tw + 14))
        for i, ln in enumerate(lines[:max_lines]):
            if i == max_lines - 1 and len(lines) > max_lines:
                ln += "…"
            cv.text(x + tw + 14 if i == 0 else x, y + 4 + i * 36, ln, "note", mix(pal.muted, pal.page, al))
