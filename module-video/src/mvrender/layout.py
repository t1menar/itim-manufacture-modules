"""Frame geometry (1080x1920 canvas), from the reference."""

from __future__ import annotations

from dataclasses import dataclass

from mvrender.fonts import FontSet

W, H = 1080, 1920

Rect = tuple[int, int, int, int]

MID: Rect = (40, 400, 1040, 1130)  # terminal / debugger / full-size diagram
PANEL: Rect = (40, 1160, 1040, 1560)  # diagram card under the terminal
NOTE_Y = 312
CAPTION_X = 60
CAPTION_Y = 166
CAPTION_LH = 68
CAPTION_MAX_W = 960
LINE_H = 40
CODE_LH = 31
WATCH_H = 178
TERM_X = MID[0] + 32
TERM_Y = MID[1] + 56 + 24
CODE_X0 = MID[0] + 116
CODE_TOP = MID[1] + 106


@dataclass(frozen=True, slots=True)
class Geometry:
    term_cols: int
    code_cols: int


def geometry(fonts: FontSet) -> Geometry:
    """Column counts follow the monospaced font's advance width."""
    return Geometry(
        term_cols=int((MID[2] - TERM_X - 24) // fonts.advance("term")),
        code_cols=int((MID[2] - 24 - CODE_X0) // fonts.advance("code")),
    )


def slot_centers(layout: str, rect: Rect) -> list[float]:
    """x of each slot of a diagram layout inside `rect`."""
    n = {"single": 1, "row2": 2, "row3": 3, "row4": 4, "pair": 2}[layout]
    x0, _, x1, _ = rect
    if layout == "pair":
        return [x0 + 180.0, x1 - 180.0]
    span = x1 - x0
    return [x0 + span * (i + 0.5) / n for i in range(n)] if n > 1 else [(x0 + x1) / 2]
