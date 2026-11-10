"""Diagrams: the bottom `panel` of a scene and the full-size `diagram` scene body."""

from __future__ import annotations

import itertools
from typing import Any

from mvrender import timing as tm
from mvrender.draw import elements as el
from mvrender.draw.canvas import Canvas, parse_markup
from mvrender.draw.captions import ramp
from mvrender.draw.debugger import step_at
from mvrender.layout import MID, PANEL, Rect, slot_centers
from mvrender.palette import WHITE, mix


def card(cv: Canvas, rect: Rect) -> None:
    cv.d.rounded_rectangle(rect, radius=24, fill=WHITE, outline=cv.pal.faint, width=2)


def element_alpha(e: dict[str, Any], t: float, marks: dict[str, float]) -> float:
    start = tm.anchor_time(e.get("appear"), marks, 0.0)
    a = ramp(t, start, 0.4)
    if e.get("disappear"):
        a *= 1 - ramp(t, tm.anchor_time(e["disappear"], marks), 0.3)
    return a


def draw_diagram(
    cv: Canvas,
    d: dict[str, Any],
    rect: Rect,
    scene: dict[str, Any],
    st: tm.SceneTiming,
    t: float,
    timing: tm.Timing,
    ref_name: str,
    captures: dict[str, str],
) -> None:
    pal = cv.pal
    x0, y0, x1, y1 = rect
    card(cv, rect)
    marks = st.marks
    layout = d["layout"]
    xs = slot_centers(layout, rect)
    cy = (y0 + y1) / 2 - 10
    full = rect == MID
    if d.get("heading"):
        p0 = ramp(t, 0.2, 0.4)
        cv.text(x0 + 50, y0 + 40, d["heading"], "h2", mix(pal.ink, WHITE, p0))
    if full:
        cy = y0 + 330
        p1 = ramp(t, 0.5, 0.4)
        col = mix(pal.accent, WHITE, p1)
        bx0, by0, bx1, by1 = x0 + 40, y0 + 140, x1 - 40, y0 + 520
        for xx in range(int(bx0 + 10), int(bx1 - 10), 26):
            cv.d.line((xx, by0, xx + 13, by0), fill=col, width=3)
            cv.d.line((xx, by1, xx + 13, by1), fill=col, width=3)
        for yy in range(int(by0 + 10), int(by1 - 10), 26):
            cv.d.line((bx0, yy, bx0, yy + 13), fill=col, width=3)
            cv.d.line((bx1, yy, bx1, yy + 13), fill=col, width=3)
    elems = d["elements"]
    by_slot: dict[int, list[dict[str, Any]]] = {}
    for e in elems:
        by_slot.setdefault(e["slot"], []).append(e)
    label_index = 0
    status_step = step_at(st, t) if scene.get("debugger") else 0
    for e in elems:
        a = element_alpha(e, t, marks)
        kind = e["type"]
        cx = xs[min(e["slot"], len(xs) - 1)]
        if kind != "label" and a <= 0:
            continue
        crowded = any(
            o is not e and o["type"] not in ("pill", "arrow") and o["slot"] == e["slot"]
            for o in by_slot[e["slot"]]
        )
        if kind == "folder":
            el.folder(
                cv,
                cx,
                cy + (20 if scene.get("debugger") else -10),
                e.get("label", ""),
                e.get("name", ""),
                a,
                e.get("style", "plain"),
                e.get("sub"),
            )
        elif kind == "cylinder":
            top = y0 + 190 - 14 * (1 - a)
            el.cylinder(cv, cx, top, e.get("name", ""), e.get("sub", ""), a, e.get("style") == "template")
        elif kind == "pill":
            if e.get("follow"):
                step = scene["debugger"]["steps"][status_step]
                text = step["status"]
                pa = ramp(t, st.steps[status_step].start, 0.35)
                resume = marks.get("debugger.resume", 1e9)
                if t >= resume:
                    el.pill(
                        cv, cx, y0 + 46, scene["debugger"]["steps"][-1]["status"], 1.0, pal.accent, solid=True
                    )
                else:
                    el.pill(cv, cx, y0 + 46 - 8 * (1 - pa), text, pa, pal.accent)
            else:
                py = cy - 88 if crowded else cy + 20
                role = "crumb" if crowded else "pill"
                el.pill(
                    cv,
                    cx,
                    py,
                    e.get("text", ""),
                    a,
                    pal.accent if e.get("style") != "dark" else pal.ink,
                    role=role,
                    solid=e.get("style") in ("dark", "accent"),
                    pad=14 if crowded else 18,
                )
        elif kind == "arrow":
            xa, xb = xs[e.get("from_slot", 0)] + 120, xs[e.get("to_slot", 1)] - 120
            el.arrow(
                cv,
                xa,
                cy + 20,
                xb,
                a * 0.7,
                pal.accent if e.get("style") == "accent" else pal.muted,
                dashed=True,
            )
        elif kind == "counter":
            text = (
                f"{e['value']['text']} {e.get('text', '')}".strip() if e.get("value") else e.get("text", "")
            )
            colour = mix(pal.ink, WHITE, a)
            # Counters sit side by side: a text wider than its slot shrinks, then wraps by words.
            gaps = [abs(q - p) for p, q in itertools.pairwise(xs)]
            edge = 2 * min(cx - rect[0], rect[2] - cx)  # a slot near the panel edge has less room
            avail = min([edge, *gaps]) - 16
            size = cv.fonts.get("card_body").size
            lines = [text]
            if avail:
                while size > 22 and cv.width("card_body", text, size) > avail:
                    size -= 2
                if cv.width("card_body", text, size) > avail:
                    lines = [""]
                    for word in text.split():
                        trial = f"{lines[-1]} {word}".strip()
                        if lines[-1] and cv.width("card_body", trial, size) > avail:
                            lines.append(word)
                        else:
                            lines[-1] = trial
            for k, line in enumerate(lines):
                cv.centered(cx, cy - 150 + k * (size * 1.3), line, "card_body", colour, size=size)
        elif kind == "equals":
            mid = (xs[0] + xs[min(1, len(xs) - 1)]) / 2
            cv.centered(mid, cy - 70, "=", "big", mix(pal.accent, WHITE, a))
        elif kind == "number":
            cv.centered(cx, cy + 2, e["value"]["text"], "label", mix(pal.accent_text, WHITE, a))
        elif kind == "code_card":
            el.code_card(
                cv,
                rect,
                e["file_path"] if "file_path" in e else scene_path(scene, e),
                e["rows"],
                e.get("highlight"),
                e.get("text", ""),
                ref_name,
                a,
            )
        elif kind == "label":
            if a > 0:
                el.numbered_label(cv, rect, label_index, e.get("text", ""), a)
            label_index += 1
        elif kind == "pages_flow":
            step_id = (e.get("follow") or {}).get("step")
            step = next(s for s in scene["debugger"]["steps"] if s["id"] == step_id)
            stt = next(s for s in st.steps if s.id == step_id)
            xa, xb = xs[e.get("from_slot", 0)] + 120, xs[e.get("to_slot", 2)] - 120
            starts = _loop_starts(step, stt, st, timing, captures)
            done = el.flow_blocks(cv, xa, xb, cy + 20, starts, t)
            if t < marks.get("debugger.resume", 1e9):
                total = e["value"]["text"] if e.get("value") else str(len(starts))
                cv.centered(
                    (x0 + x1) / 2,
                    y1 - 54,
                    f"{e.get('text', '')} {done} / {total}".strip(),
                    "small",
                    mix(pal.ink, WHITE, a),
                )
        elif kind == "frame":
            cv.d.rounded_rectangle(
                (cx - 120, cy - 90, cx + 120, cy + 90), radius=16, outline=mix(pal.accent, WHITE, a), width=3
            )
    if d.get("footer"):
        fa = ramp(t, tm.anchor_time(d.get("footer_at"), marks, 0.4), 0.4)
        cv.segments(
            (x0 + x1) / 2 - cv.width("small", d["footer"].replace("*", "")) / 2,
            y1 - 54,
            parse_markup(d["footer"], pal.ink, pal.accent_text),
            "small",
            fa,
            WHITE,
        )


def scene_path(scene: dict[str, Any], e: dict[str, Any]) -> str:
    return str(e.get("path") or e.get("file", ""))


def _loop_starts(
    step: dict[str, Any], stt: tm.StepTiming, st: tm.SceneTiming, timing: tm.Timing, captures: dict[str, str]
) -> list[float]:
    """Time each loop iteration begins, from the step's marks."""
    n = int(float(captures.get(step["loop"]["iterations"]["capture"], "1")))
    first = stt.start + tm.STEP_LEAD_S
    out = [first]
    for i in range(n - 1):
        out.append(st.marks.get(f"{step['id']}.loop.{i}", first))
    return out


__all__ = ["PANEL", "draw_diagram"]
