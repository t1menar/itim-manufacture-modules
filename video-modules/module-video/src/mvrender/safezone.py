"""Reels safe zone: the app UI covers ~220 px on top, ~400 px at the bottom and the right column.

The frame is laid out on the full canvas and scaled into the free area; every box drawn is recorded
so the check can prove it ended up inside the safe rectangle.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from mvrender.layout import H, W

SAFE_SRC = (0, 150, 1080, 1590)  # what the layout fills
SAFE_SCALE = 0.9
SAFE_POS = (36, 220)  # -> x 72..972, y 220..1516


@dataclass(frozen=True, slots=True)
class SafeRect:
    top: int = 220
    bottom: int = 400  # free pixels kept at the bottom
    left: int = 72
    right: int = 108  # free pixels kept at the right

    def bounds(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, W - self.right, H - self.bottom)


def transform(x: float, y: float) -> tuple[float, float]:
    """Canvas layout coordinates to final frame coordinates."""
    return (x - SAFE_SRC[0]) * SAFE_SCALE + SAFE_POS[0], (y - SAFE_SRC[1]) * SAFE_SCALE + SAFE_POS[1]


def outside(box: tuple[float, float, float, float], safe: SafeRect) -> float:
    """Pixels by which a layout box, once transformed, leaves the safe rectangle (0 = inside)."""
    x0, y0 = transform(box[0], box[1])
    x1, y1 = transform(box[2], box[3])
    sl, st, sr, sb = safe.bounds()
    return max(0.0, sl - x0, st - y0, x1 - sr, y1 - sb)


def _dots() -> np.ndarray:
    m = Image.new("L", (W, H), 0)
    dd = ImageDraw.Draw(m)
    for yy in range(24, H, 36):
        for xx in range(24, W, 36):
            dd.ellipse((xx - 1.6, yy - 1.6, xx + 1.6, yy + 1.6), fill=255)
    return np.asarray(m) > 127


_DOTS: np.ndarray | None = None


def to_reels(img: Image.Image, page: tuple[int, int, int], grid: tuple[int, int, int]) -> Image.Image:
    """Scale the laid-out frame into the safe zone and add the dotted page background."""
    global _DOTS
    if _DOTS is None:
        _DOTS = _dots()
    src = img.crop(SAFE_SRC)
    src = src.resize(
        (round(src.width * SAFE_SCALE), round(src.height * SAFE_SCALE)), Image.Resampling.LANCZOS
    )
    out = Image.new("RGB", (W, H), page)
    out.paste(src, SAFE_POS)
    a = np.asarray(out).copy()
    plain = np.all(a == np.array(page, dtype=a.dtype), axis=2)
    a[plain & _DOTS] = grid
    return Image.fromarray(a)
