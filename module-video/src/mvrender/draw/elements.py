"""Diagram vocabulary: folder, cylinder, pill, arrow, counter, equals, code card, label, ..."""

from __future__ import annotations

import math
from typing import Any

from mvrender.draw.canvas import Canvas, parse_markup
from mvrender.draw.captions import ramp, wrap_words
from mvrender.draw.highlight_c import highlight_c
from mvrender.layout import Rect
from mvrender.palette import CARD_EDGE, WHITE, mix


def folder(
    cv: Canvas,
    cx: float,
    cy: float,
    label: str,
    name: str,
    a: float,
    style: str,
    sub: str | None = None,
    scale: float = 1.0,
    w: float = 210,
    h: float = 150,
) -> None:
    if a <= 0:
        return
    pal = cv.pal
    w, h = w * scale, h * scale
    x0, y0 = cx - w / 2, cy - h / 2
    if style == "new":
        body, edge, lab = pal.accent, pal.accent_text, WHITE
    elif style == "template":
        body, edge, lab = pal.accent_light, pal.accent, pal.ink
    else:
        body, edge, lab = WHITE, CARD_EDGE, pal.ink
    body, edge, lab = mix(body, WHITE, a), mix(edge, WHITE, a), mix(lab, WHITE, a)
    cv.d.rounded_rectangle(
        (x0, y0 - 18 * scale, x0 + w * 0.42, y0 + 10), radius=int(8 * scale), fill=body, outline=edge, width=3
    )
    cv.d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=int(14 * scale), fill=body, outline=edge, width=3)
    cv.centered(cx, cy - 18, label, "label", lab)
    cv.centered(
        cx,
        y0 + h + 12,
        name,
        "small",
        mix(pal.accent_text if style in ("new", "template") else pal.muted, WHITE, a),
    )
    if sub:
        cv.centered(cx, y0 + h + 46, sub, "crumb", mix(pal.muted, WHITE, a))


def cylinder(cv: Canvas, cx: float, top: float, name: str, sub: str, a: float, strong: bool) -> None:
    pal = cv.pal
    w, h, eh = 210, 200, 36
    fill = mix(pal.accent if strong else pal.accent_light, WHITE, a)
    edge = mix(pal.accent_text if strong else pal.accent, WHITE, a)
    cv.d.ellipse((cx - w / 2, top + h - eh, cx + w / 2, top + h), fill=fill, outline=edge, width=3)
    cv.d.rectangle((cx - w / 2, top + eh / 2, cx + w / 2, top + h - eh / 2), fill=fill)
    for sx in (cx - w / 2, cx + w / 2 - 1):
        cv.d.line((sx, top + eh / 2, sx, top + h - eh / 2), fill=edge, width=3)
    cv.d.ellipse(
        (cx - w / 2, top, cx + w / 2, top + eh),
        fill=mix(pal.accent_top if strong else WHITE, WHITE, a),
        outline=edge,
        width=3,
    )
    for j, item in enumerate(s.strip() for s in sub.split("·") if s.strip()):
        cv.centered(
            cx,
            top + 58 + j * 34,
            item,
            "crumb",
            mix(WHITE if strong else pal.ink, pal.accent if strong else pal.accent_light, a),
        )
    cv.centered(cx, top + 222, name, "pill", mix(pal.accent_text if strong else pal.ink, WHITE, a))


def arrow(
    cv: Canvas,
    x0: float,
    y: float,
    x1: float,
    a: float,
    color: tuple[int, int, int],
    dashed: bool = False,
    width: int = 4,
) -> None:
    col = mix(color, WHITE, a)
    if dashed:
        x = x0
        while x < x1 - 20:
            cv.d.line((x, y, min(x + 14, x1 - 20), y), fill=col, width=width)
            x += 26
    else:
        cv.d.line((x0, y, x1 - 16, y), fill=col, width=width)
    cv.d.polygon([(x1, y), (x1 - 22, y - 13), (x1 - 22, y + 13)], fill=col)


def pill(
    cv: Canvas,
    cx: float,
    cy: float,
    text: str,
    a: float,
    fg: tuple[int, int, int],
    *,
    role: str = "pill",
    solid: bool = False,
    pad: int = 18,
) -> None:
    if a <= 0:
        return
    pal = cv.pal
    plain = text.replace("*", "")
    tw = cv.width(role, plain)
    bb = cv.fonts.get(role).getbbox("Ag")
    hgt = bb[3] - bb[1] + pad
    x0 = cx - tw / 2 - pad
    fill = mix(fg if solid else mix(fg, WHITE, 0.12), WHITE, a)
    cv.d.rounded_rectangle(
        (x0, cy - hgt / 2, cx + tw / 2 + pad, cy + hgt / 2),
        radius=int(hgt / 2),
        fill=fill,
        outline=mix(fg, WHITE, a),
        width=2,
    )
    segs = parse_markup(text, WHITE if solid else pal.ink, WHITE if solid else pal.accent_text)
    cv.segments(x0 + pad, cy - hgt / 2 + pad / 2 - bb[1], segs, role, a, fill if solid else WHITE)


def code_card(
    cv: Canvas,
    rect: Rect,
    file_path: str,
    rows: list[dict[str, Any]],
    highlight: int | None,
    note: str,
    ref_name: str,
    a: float,
) -> None:
    """Small dark block with real source lines inside the white panel."""
    pal = cv.pal
    x0, y0, x1, _ = rect
    bx0, by0, bx1 = x0 + 30, y0 + 28, x1 - 30
    room = (bx1 - cv.width("crumb", ref_name)) - bx0 - 24  # the ref name sits on the same row
    cv.text(bx0, by0, cv.fit_tail("crumb", file_path, room), "crumb", mix(pal.muted, WHITE, a))
    cv.text(bx1 - cv.width("crumb", ref_name), by0, ref_name, "crumb", mix(pal.accent_text, WHITE, a))
    lines = [(r["n"], r["text"].expandtabs(4)) for r in rows]
    ind = min((len(t) - len(t.lstrip()) for _, t in lines if t.strip()), default=0)
    by = by0 + 38
    hgt = len(lines) * 32 + 22
    cv.d.rounded_rectangle((bx0, by, bx1, by + hgt), radius=14, fill=mix(pal.win, WHITE, a))
    yy = by + 11
    in_com = False
    code_w = cv.fonts.advance("code")
    for n, txt in lines:
        txt = txt[ind:]
        if len(txt) > 60:
            txt = txt[:59] + "…"
        if n == highlight:
            cv.d.rectangle((bx0, yy - 3, bx1, yy + 29), fill=mix(mix(pal.accent, pal.win, 0.25), WHITE, a))
        num = str(n)
        cv.text(
            bx0 + 76 - code_w * len(num),
            yy,
            num,
            "code",
            mix(pal.accent if n == highlight else pal.win_dim, WHITE, a),
        )
        segs, in_com = highlight_c(txt, in_com, pal)
        cv.segments(bx0 + 96, yy, segs, "code_current" if n == highlight else "code", a, pal.win)
        yy += 32
    for i, ln in enumerate(wrap_words(cv, note, "small", bx1 - bx0)):
        cv.segments(
            bx0, by + hgt + 16 + i * 34, parse_markup(ln, pal.ink, pal.accent_text), "small", a, WHITE
        )


def flow_blocks(cv: Canvas, xa: float, xb: float, cy: float, starts: list[float], t: float) -> int:
    """Small page blocks travelling from `xa` to `xb`; returns how many have arrived."""
    pal = cv.pal
    done = 0
    for b, (sa, ea) in enumerate(starts_to_spans(starts)):
        q = (t - sa) / max(0.3, ea - sa)
        if q >= 1:
            done += 1
        if 0 < q < 1:
            e = 3 * q * q - 2 * q**3
            x = xa + (xb - xa) * e
            y = cy + ((b % 3) - 1) * 26 * math.sin(q * math.pi)
            cv.d.rounded_rectangle(
                (x - 12, y - 15, x + 12, y + 15), radius=4, fill=pal.accent if q > 0.5 else pal.flow_light
            )
    return done


def starts_to_spans(starts: list[float]) -> list[tuple[float, float]]:
    return [(s, (starts[i + 1] if i + 1 < len(starts) else s + 0.5)) for i, s in enumerate(starts)]


def numbered_label(cv: Canvas, rect: Rect, index: int, text: str, a: float) -> None:
    pal = cv.pal
    yy = rect[1] + 60 + index * 84
    cv.d.ellipse((90, yy - 4, 142, yy + 48), fill=mix(pal.accent, WHITE, a))
    n = str(index + 1)
    cv.text(116 - cv.width("card_body", n) / 2, yy + 4, n, "card_body", WHITE)
    cv.segments(166, yy + 6, parse_markup(text, pal.ink, pal.accent_text), "card_body", a, WHITE)


__all__ = ["ramp"]
