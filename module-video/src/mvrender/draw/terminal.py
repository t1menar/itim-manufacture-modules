"""Terminal window: a state machine over the timed events."""

from __future__ import annotations

from typing import Any

from mvrender import timing as tm
from mvrender.draw.canvas import Canvas
from mvrender.draw.highlight_c import Segments
from mvrender.draw.highlight_sh import highlight_cmd, output_row, wrap_output
from mvrender.layout import LINE_H, MID, TERM_X, TERM_Y, Geometry


def draw_window_frame(cv: Canvas, rect: tuple[int, int, int, int], title: str) -> None:
    pal = cv.pal
    x0, y0, x1, _ = rect
    cv.d.rounded_rectangle(rect, radius=22, fill=pal.win)
    cv.d.rounded_rectangle((x0, y0, x1, y0 + 56), radius=22, fill=pal.win_bar)
    cv.d.rectangle((x0, y0 + 34, x1, y0 + 56), fill=pal.win_bar)
    cv.d.line((x0, y0 + 56, x1, y0 + 56), fill=pal.win_line, width=2)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cv.d.ellipse((x0 + 24 + i * 34, y0 + 18, x0 + 44 + i * 34, y0 + 38), fill=c)
    tw = cv.width("window_title", title)
    cv.text((x0 + x1) / 2 - tw / 2 + 40, y0 + 15, title, "window_title", pal.win_muted)


def _break_points(line: str, cols: int) -> list[int]:
    """Where a terminal soft-wraps `line`: after the last space that fits, else at the column limit."""
    points: list[int] = []
    start = 0
    while len(line) - start > cols:
        window = line[start : start + cols]
        cut = window.rfind(" ") + 1
        cut = cut if cut > 10 else cols
        start += cut
        points.append(start)
    return points


def wrap_segments(segs: Segments, points: list[int]) -> list[Segments]:
    """Split highlighted `segs` at the flat character offsets `points`."""
    rows: list[Segments] = [[]]
    pos, bounds = 0, iter(points)
    nxt = next(bounds, None)
    for text, color in segs:
        while text:
            if nxt is not None and pos + len(text) > nxt:
                head = text[: nxt - pos]
                if head:
                    rows[-1].append((head, color))
                text, pos = text[nxt - pos :], nxt
                rows.append([])
                nxt = next(bounds, None)
            else:
                rows[-1].append((text, color))
                pos += len(text)
                text = ""
    return rows


def _ease(x: float) -> float:
    return max(0.0, min(1.0, x))


def terminal_state(
    tt: tm.TerminalTiming, t: float, cv: Canvas, geo: Geometry, upto_resume: float | None = None
) -> tuple[list[Segments], tuple[int, int] | None]:
    """Rows to show at scene time `t` and the cursor (row, column), if any."""
    pal = cv.pal
    rows: list[Segments] = []
    cursor: tuple[int, int] | None = None
    last_cmd: dict[str, Any] | None = None
    highlights: dict[str, list[str]] = {}
    for ev in tt.events:
        if ev.t > t:
            break
        if ev.kind == "cmd":
            spec = ev.payload
            last_cmd = spec
            highlights[ev.ref] = spec.get("highlight", [])
            text = str(spec["text"])
            p = _ease((t - ev.t) / ev.dur) if ev.dur > 0 else 1.0
            n = round(len(text) * p)
            prompt = str(spec.get("prompt", ""))
            # A typed command longer than the window soft-wraps like in a real terminal; the break
            # points come from the whole line so the wrap does not jump while it is being typed.
            points = _break_points(prompt + text, geo.term_cols - 2)
            wrapped = wrap_segments([(prompt, pal.accent), *highlight_cmd(text[:n], pal)], points)
            first = len(rows)
            for k, seg in enumerate(wrapped):
                rows.append(seg if k == 0 else [("  ", pal.accent), *seg])
            if p < 1:
                idx = len(prompt) + n
                k = sum(1 for b in points if b <= idx)
                start = points[k - 1] if k else 0
                cursor = (first + k, idx - start + (2 if k else 0))
            else:
                cursor = None
        elif ev.kind == "out":
            cid, k = ev.payload
            spec = next(e for e in _cmd_events(tt) if e.ref == cid).payload
            for chunk, kind in wrap_output(str(spec["rows"][k]), geo.term_cols):
                rows.append(output_row(chunk, highlights.get(cid, []), pal, kind))
            cursor = None
        elif ev.kind == "annotation":
            rows.append(output_row(str(ev.payload), [], pal))
            cursor = None
    if last_cmd is not None and t >= tt.end - 1e-9 and tt.events:
        prompt = str(last_cmd.get("prompt_after", ""))
        rows.append([(prompt, pal.accent)])
        cursor = (len(rows) - 1, len(prompt))
    return rows, cursor


def _cmd_events(tt: tm.TerminalTiming) -> list[tm.TermEvent]:
    return [e for e in tt.events if e.kind == "cmd"]


def draw_terminal(
    cv: Canvas, tt: tm.TerminalTiming, title: str, t: float, abs_t: float, geo: Geometry
) -> None:
    pal = cv.pal
    y1 = MID[3]
    draw_window_frame(cv, MID, title)
    rows, cursor = terminal_state(tt, t, cv, geo)
    max_rows = int((y1 - TERM_Y - 16) // LINE_H)
    shift = max(0, len(rows) - max_rows)
    for r, segs in enumerate(rows[shift:]):
        cv.segments(TERM_X, TERM_Y + r * LINE_H, segs, "term", 1.0, pal.win)
    typing = any(a <= t <= b for a, b in tt.typing)
    if cursor and (int(abs_t * 2) % 2 == 0 or typing):
        cr, cc = cursor
        cw = cv.fonts.advance("term")
        cx = TERM_X + cc * cw
        cy = TERM_Y + (cr - shift) * LINE_H
        cv.d.rectangle((cx, cy + 3, cx + cw - 3, cy + 34), fill=pal.accent)
