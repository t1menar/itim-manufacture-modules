"""Colour tokens by name (settings `palette`); defaults are the reference values."""

from __future__ import annotations

from collections.abc import Mapping

RGB = tuple[int, int, int]

DEFAULTS: dict[str, str] = {
    "page": "#FBF8F3",
    "grid": "#EAE2D8",
    "ink": "#1F1B17",
    "muted": "#766C62",
    "faint": "#E0D7CC",
    "accent": "#FF6B00",
    "accent_text": "#DB5200",
    "accent_light": "#FFEDDE",
    "win": "#1E1A17",
    "win_bar": "#2C2723",
    "win_line": "#3E3731",
    "win_fg": "#F3EDE5",
    "win_muted": "#988D81",
    "win_dim": "#645C54",
    "watch_bg": "#24201C",
    "c_kw": "#FF913C",
    "c_type": "#FFCDA0",
    "c_str": "#FFE0BE",
    "c_num": "#FFAF5F",
    "c_comment": "#82786E",
    "c_fn": "#FFFFFF",
    "c_macro": "#FFA573",
    "err": "#FF6955",
    "err_cont": "#FF9682",
    "detail": "#FFBE5A",
    "accent_top": "#FF9646",  # lid of a strong cylinder
    "flow_light": "#FFAF6E",  # the light half of a flow marker
    "sql_kw": "#FFAA64",  # SQL keywords in shell output
}

# Fixed tones that are not themable (traffic lights, plain card edge, breakpoint).
WHITE: RGB = (255, 255, 255)
CARD_EDGE: RGB = (190, 180, 168)
BREAKPOINT: RGB = (235, 70, 50)
OUT_FG: RGB = (205, 196, 186)
CODE_FG: RGB = (226, 218, 208)
CODE_PUNCT: RGB = (196, 186, 176)


def parse_hex(value: str) -> RGB:
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


class Palette:
    """`palette.ink` and friends as RGB tuples; unknown names fall back to the defaults."""

    def __init__(self, tokens: Mapping[str, str] | None = None) -> None:
        merged = {**DEFAULTS, **(tokens or {})}
        self._rgb = {k: parse_hex(v) for k, v in merged.items()}

    def __getattr__(self, name: str) -> RGB:
        rgb: dict[str, RGB] = self.__dict__["_rgb"]
        try:
            return rgb[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, name: str) -> RGB:
        return self._rgb[name]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def mix(color: RGB, bg: RGB, alpha: float) -> RGB:
    """`color` over `bg` at `alpha` (0 = background, 1 = colour)."""
    a = clamp(alpha)
    return (
        int(bg[0] + (color[0] - bg[0]) * a),
        int(bg[1] + (color[1] - bg[1]) * a),
        int(bg[2] + (color[2] - bg[2]) * a),
    )
