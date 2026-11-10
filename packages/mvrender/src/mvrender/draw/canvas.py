"""Canvas: every text and box goes through here so the checks can see it."""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from mvrender.draw.highlight_c import Segments
from mvrender.fonts import FontSet, GlyphMissing
from mvrender.palette import RGB, Palette, mix
from mvrender.safezone import SafeRect, outside


class SafeZoneError(Exception):
    def __init__(self, scene: str, what: str, px: float) -> None:
        self.scene, self.what, self.px = scene, what, px
        super().__init__(f"safe_zone: {what!r} in scene {scene!r} is {px:.0f} px outside the safe zone")


@dataclass(slots=True)
class Record:
    scene: str
    role: str
    text: str
    box: tuple[float, float, float, float]


@dataclass
class Canvas:
    img: Image.Image
    fonts: FontSet
    pal: Palette
    scene: str = ""
    safe: SafeRect = field(default_factory=SafeRect)
    records: list[Record] = field(default_factory=list)
    strict: bool = True

    def __post_init__(self) -> None:
        self.d = ImageDraw.Draw(self.img)

    # text ---------------------------------------------------------------------------------------
    def width(self, role: str, text: str, size: float | None = None) -> float:
        return self.fonts.width(role, text, size)

    def fit_tail(self, role: str, text: str, room: float) -> str:
        """`text` shortened from the left ("...") to at most `room` px wide; a path keeps its tail."""
        while len(text) > 8 and self.width(role, text) > room:
            keep = text[3:] if text.startswith("...") else text
            text = "..." + keep[max(1, len(keep) // 12) :]
        return text

    def text(self, x: float, y: float, s: str, role: str, fill: RGB, *, size: float | None = None) -> float:
        """Draw `s`; returns its width. Missing glyphs and safe-zone breaches raise."""
        if not s:
            return 0.0
        bad = self.fonts.missing(role, s)
        if bad:
            raise GlyphMissing(bad[0], role, self.scene, s)
        w = self.width(role, s, size)
        font = self.fonts.get(role, size)
        h = font.size * 1.3
        box = (x, y, x + w, y + h)
        self.records.append(Record(self.scene, role, s, box))
        if self.strict:
            px = outside(box, self.safe)
            if px > 0.5:
                raise SafeZoneError(self.scene, s, px)
        self.d.text((x, y), s, font=font, fill=fill)
        return w

    def segments(
        self,
        x: float,
        y: float,
        segs: Segments,
        role: str,
        alpha: float = 1.0,
        bg: RGB | None = None,
        *,
        size: float | None = None,
    ) -> float:
        bg = bg or self.pal.page
        for txt, col in segs:
            x += self.text(x, y, txt, role, mix(col, bg, alpha), size=size)
        return x

    def centered(
        self, cx: float, y: float, s: str, role: str, fill: RGB, *, size: float | None = None
    ) -> None:
        self.text(cx - self.width(role, s, size) / 2, y, s, role, fill, size=size)


def parse_markup(text: str, base: RGB, accent: RGB) -> Segments:
    """`*accent*` spans."""
    out: Segments = []
    on = False
    for part in text.split("*"):
        if part:
            out.append((part, accent if on else base))
        on = not on
    return out
