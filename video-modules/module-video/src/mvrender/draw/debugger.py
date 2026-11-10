"""Debugger window: call stack, source rows, current line, watch panel."""

from __future__ import annotations

import re
from typing import Any

from mvrender import timing as tm
from mvrender.draw.canvas import Canvas
from mvrender.draw.captions import ramp
from mvrender.draw.highlight_c import Segments, highlight_c
from mvrender.draw.terminal import draw_window_frame
from mvrender.layout import CODE_LH, CODE_TOP, CODE_X0, MID, WATCH_H, Geometry
from mvrender.palette import BREAKPOINT, mix

Row = tuple[int | None, Segments, str]


def layout_step(cv: Canvas, step: dict[str, Any], geo: Geometry) -> list[Row]:
    """Display rows (line number or None, segments, kind): verbatim text, tabs to 4, common indent
    removed, soft-wrapped at the code column count."""
    raw: list[tuple[int | None, str, str]] = []
    ranges = step["ranges"]
    by_n = {r["n"]: r["text"] for r in step["rows"]}
    for ri, (a, b) in enumerate(ranges):
        if ri:
            raw.append((None, "", "gap"))
        for ln in range(a, b + 1):
            raw.append((ln, by_n[ln].expandtabs(4), "line"))
    ind = min((len(t) - len(t.lstrip()) for _, t, kd in raw if kd == "line" and t.strip()), default=0)
    rows: list[Row] = []
    in_com = False
    for n, t, kd in raw:
        if kd == "gap":
            rows.append((None, [], "gap"))
            continue
        segs, in_com = highlight_c(t[ind:], in_com, cv.pal)
        line: Segments = []
        used = 0
        first = True
        toks = [(tk, col) for txt, col in segs for tk in re.findall(r"\s+|\S+", txt)]
        for tk, col in toks:
            if used + len(tk) > geo.code_cols and used > 4 and tk.strip():
                rows.append((n, line, "line" if first else "cont"))
                first = False
                line, used = [("        ", col)], 8
            if not tk.strip() and used == 8 and not first:
                continue
            line.append((tk, col))
            used += len(tk)
        rows.append((n, line, "line" if first else "cont"))
    return rows


def step_at(st: tm.SceneTiming, t: float) -> int:
    idx = 0
    for i, s in enumerate(st.steps):
        if s.start <= t:
            idx = i
    return idx


def visits(
    step: dict[str, Any], start: float, timing: tm.Timing, iters: int | None
) -> list[tuple[int, float]]:
    """(line, time it becomes current) for every line visit of the step."""
    out: list[tuple[int, float]] = []
    t = start + tm.STEP_LEAD_S
    for n, hold, _name in tm.line_holds(step, timing, iters):
        if n:
            out.append((n, t))
        t += hold
    return out


def draw_debugger(
    cv: Canvas,
    scene: dict[str, Any],
    st: tm.SceneTiming,
    t: float,
    timing: tm.Timing,
    geo: Geometry,
    captures: dict[str, str],
    ref_name: str,
) -> None:
    pal = cv.pal
    x0, y0, x1, y1 = MID
    k = step_at(st, t)
    step = scene["debugger"]["steps"][k]
    stt = st.steps[k]
    lt = t - stt.start
    draw_window_frame(cv, MID, step["path"])
    cv.d.rectangle((x0, y0 + 58, x1, y0 + 94), fill=pal.watch_bg)
    bx = float(x0 + 24)
    cv.d.ellipse((bx, y0 + 69, bx + 14, y0 + 83), fill=pal.win_accent)
    cv.text(bx + 24, y0 + 65, "paused", "crumb", pal.win_accent)
    bx += 24 + cv.width("crumb", "paused") + 22
    for i, p in enumerate(step["stack"]):
        last = i == len(step["stack"]) - 1
        label = p + ("()" if last else "")
        cv.text(bx, y0 + 65, label, "crumb", pal.win_fg if last else pal.win_muted)
        bx += cv.width("crumb", label)
        if not last:
            cv.text(bx + 8, y0 + 65, "›", "crumb", pal.win_dim)
            bx += 30
    if bx + 40 < x1 - 24 - cv.width("crumb", ref_name):
        cv.text(x1 - 24 - cv.width("crumb", ref_name), y0 + 65, ref_name, "crumb", pal.win_dim)

    iters = _iters(step, captures)
    vs = visits(step, stt.start, timing, iters)
    si = max([i for i, (_, vt) in enumerate(vs) if vt <= t] or [-1])
    cur_line = vs[si][0] if si >= 0 else None
    seen = {n for n, _ in vs[: max(si, 0)]}
    first_line = vs[0][0] if vs else None
    appear = ramp(lt, 0.0, 0.3)
    watch_top = y1 - WATCH_H
    y, gut_x = float(CODE_TOP), x0 + 16
    code_w = cv.fonts.advance("code")
    for n, segs, kind in layout_step(cv, step, geo):
        if y > watch_top - CODE_LH:
            break
        if kind == "gap":
            for j in range(3):
                cv.d.ellipse((gut_x + 30 + j * 10, y + 13, gut_x + 35 + j * 10, y + 18), fill=pal.win_dim)
            y += CODE_LH
            continue
        is_cur = cur_line is not None and n == cur_line
        if is_cur:
            cv.d.rectangle((x0 + 2, y - 3, x1 - 2, y + CODE_LH - 3), fill=mix(pal.win_accent, pal.win, 0.22))
            cv.d.rectangle((x0 + 2, y - 3, x0 + 7, y + CODE_LH - 3), fill=pal.win_accent)
        if kind == "line" and n is not None:
            num = str(n)
            col = pal.win_accent if is_cur else (pal.win_muted if n in seen else pal.win_dim)
            cv.text(CODE_X0 - 18 - code_w * len(num), y, num, "code", mix(col, pal.win, appear))
            if n == first_line:
                cv.d.ellipse((gut_x - 4, y + 7, gut_x + 10, y + 21), fill=mix(BREAKPOINT, pal.win, appear))
            if is_cur:
                cv.d.polygon(
                    [(gut_x + 14, y + 6), (gut_x + 25, y + 14), (gut_x + 14, y + 22)], fill=pal.win_accent
                )
        cv.segments(
            CODE_X0,
            y,
            segs,
            "code_current" if is_cur else "code",
            appear * (1.0 if (is_cur or cur_line is None) else 0.82),
            pal.win,
        )
        y += CODE_LH
    cv.d.line((x0, watch_top, x1, watch_top), fill=pal.win_line, width=2)
    cv.d.rounded_rectangle((x0 + 2, watch_top + 2, x1 - 2, y1 - 2), radius=20, fill=pal.watch_bg)
    cv.d.rectangle((x0 + 2, watch_top + 2, x1 - 2, watch_top + 24), fill=pal.watch_bg)
    cv.text(x0 + 26, watch_top + 14, "WATCH", "crumb", pal.win_muted)
    vals: dict[str, tuple[str, float]] = {}
    order: list[str] = []
    for w in step.get("watch", []):
        if w["at"] <= si:
            if w["name"] not in vals:
                order.append(w["name"])
            vals[w["name"]] = (w["value"]["text"], vs[w["at"]][1] if w["at"] < len(vs) else stt.start)
    wy = watch_top + 46
    for name in order[-4:]:
        val, ch = vals[name]
        flash = 1 - max(0.0, min(1.0, (t - ch) / 0.9))
        if flash > 0:
            cv.d.rounded_rectangle(
                (x0 + 18, wy - 3, x1 - 18, wy + 28),
                radius=6,
                fill=mix(pal.win_accent, pal.watch_bg, 0.30 * flash),
            )
        cv.text(x0 + 30, wy, name, "code", pal.win_muted)
        cv.text(x0 + 30 + cv.width("code", name + " "), wy, "=", "code", pal.win_dim)
        cv.text(
            x0 + 30 + cv.width("code", name + " = "),
            wy,
            val,
            "code_current",
            mix(pal.win_accent, pal.win_fg, 0.4 + 0.6 * flash),
        )
        wy += 31


def _iters(step: dict[str, Any], captures: dict[str, str]) -> int | None:
    loop = step.get("loop")
    if not loop:
        return None
    return max(0, int(float(captures.get(loop["iterations"]["capture"], "1"))))
