"""Fonts by role. Only Inter and JetBrains Mono from the image directory are ever loaded.

There is no fallback font: a missing glyph would be drawn as `.notdef`, which is why every string
is checked against the font's character map (`has_glyph`) before it is drawn.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

DEFAULT_DIR = Path(os.environ.get("MVRENDER_FONTS", "/usr/share/fonts/manufacture"))


@dataclass(frozen=True, slots=True)
class Role:
    file: str
    size: int


# Sizes are the reference's; the reference weights map to Inter SemiBold and JetBrains Mono.
ROLES: dict[str, Role] = {
    "caption": Role("Inter-Bold.ttf", 60),
    "note_term": Role("Inter-SemiBold.ttf", 24),
    "note": Role("Inter-Medium.ttf", 25),
    "small": Role("Inter-Medium.ttf", 24),
    "pill": Role("Inter-SemiBold.ttf", 26),
    "card_title": Role("Inter-Bold.ttf", 40),
    "card_body": Role("Inter-Medium.ttf", 30),
    "big": Role("Inter-Bold.ttf", 84),
    "h2": Role("Inter-SemiBold.ttf", 34),
    "term": Role("JetBrainsMono-Regular.ttf", 27),
    "code": Role("JetBrainsMono-Regular.ttf", 22),
    "code_current": Role("JetBrainsMono-SemiBold.ttf", 22),
    "window_title": Role("JetBrainsMono-Medium.ttf", 21),
    "crumb": Role("JetBrainsMono-Regular.ttf", 19),
    "label": Role("JetBrainsMono-SemiBold.ttf", 24),
}


class FontError(Exception):
    pass


class GlyphMissing(FontError):
    """A string needs a character the role's font does not have."""

    def __init__(self, char: str, role: str, scene: str, text: str) -> None:
        self.char, self.role, self.scene, self.text = char, role, scene, text
        super().__init__(
            f"missing glyph {char!r} (U+{ord(char):04X}) in role {role!r}, scene {scene!r}, text {text!r}"
        )


class FontSet:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory else DEFAULT_DIR
        self._fonts: dict[str, ImageFont.FreeTypeFont] = {}
        self._cmaps: dict[str, frozenset[int]] = {}

    def path(self, role: str) -> Path:
        return self.directory / ROLES[role].file

    def get(self, role: str, size: int | None = None) -> ImageFont.FreeTypeFont:
        """The font for `role`; `size` overrides the role size (caption shrinking)."""
        spec = ROLES[role]
        key = f"{role}:{size or spec.size}"
        if key not in self._fonts:
            try:
                self._fonts[key] = ImageFont.truetype(str(self.directory / spec.file), size or spec.size)
            except OSError as exc:
                raise FontError(f"font file {spec.file} not found in {self.directory}") from exc
        return self._fonts[key]

    def cmap(self, role: str) -> frozenset[int]:
        file = ROLES[role].file
        if file not in self._cmaps:
            font = TTFont(str(self.directory / file), lazy=True)
            self._cmaps[file] = frozenset(font.getBestCmap())
        return self._cmaps[file]

    def has_glyph(self, role: str, char: str) -> bool:
        return char in ("\n", "\t") or ord(char) in self.cmap(role)

    def missing(self, role: str, text: str) -> list[str]:
        return [c for c in dict.fromkeys(text) if not self.has_glyph(role, c)]

    def width(self, role: str, text: str, size: int | None = None) -> float:
        return float(self.get(role, size).getlength(text))

    def advance(self, role: str) -> float:
        """Width of one character of a monospaced role."""
        return float(self.get(role).getlength("M"))


@lru_cache(maxsize=4)
def fonts_in(directory: str) -> FontSet:
    return FontSet(directory)
