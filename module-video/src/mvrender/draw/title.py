"""Title scene body: big lines centred in the main area."""

from __future__ import annotations

from typing import Any

from mvrender.draw.canvas import Canvas, parse_markup
from mvrender.draw.captions import ramp
from mvrender.layout import MID
from mvrender.palette import mix


def draw_title(cv: Canvas, title: dict[str, Any], t: float) -> None:
    pal = cv.pal
    x0, y0, x1, y1 = MID
    cv.d.rounded_rectangle(MID, radius=24, fill=(255, 255, 255), outline=pal.faint, width=2)
    lines = title["lines"]
    top = (y0 + y1) / 2 - len(lines) * 50
    for i, line in enumerate(lines):
        start = 0.2 + (1.2 * i if title.get("reveal") == "by_line" else 0.0)
        a = ramp(t, start, 0.4)
        plain = line.replace("*", "")
        w = cv.width("card_title", plain)
        cv.segments(
            (x0 + x1) / 2 - w / 2,
            top + i * 100,
            parse_markup(line, pal.ink, pal.accent_text),
            "card_title",
            a,
            (255, 255, 255),
        )
    if title.get("footer"):
        cv.centered(
            (x0 + x1) / 2, y1 - 60, title["footer"], "small", mix(pal.muted, (255, 255, 255), ramp(t, 1.0))
        )
