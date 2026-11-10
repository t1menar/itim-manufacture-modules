"""Per-system colour schemes: a video about a system wears that system's own colours."""

from __future__ import annotations

from typing import Any

# Apache Kafka's icon is black on white: the page turns white, the accent graphite black, and the
# terminal window and code tones go neutral (a warm tint would read as another brand).
KAFKA: dict[str, str] = {
    "page": "#FFFFFF",
    "grid": "#E9E9E9",
    "ink": "#231F20",
    "muted": "#6E6A6B",
    "faint": "#DDDDDD",
    "accent": "#231F20",
    "accent_text": "#231F20",
    "accent_light": "#ECECEC",
    "win": "#1B1819",
    "win_bar": "#2A2627",
    "win_line": "#3A3637",
    "win_fg": "#F4F4F4",
    "win_muted": "#9B9798",
    "win_dim": "#686465",
    "watch_bg": "#222021",
    "c_kw": "#FFFFFF",
    "c_type": "#D8D6D7",
    "c_str": "#BDBBBC",
    "c_num": "#E8E7E7",
    "c_comment": "#807C7D",
    "c_fn": "#FFFFFF",
    "c_macro": "#CFCDCE",
    "err": "#FF6955",
    "err_cont": "#FF9682",
    "detail": "#CFCDCE",
    "accent_top": "#6E6A6B",
    "flow_light": "#8E8A8B",
    "sql_kw": "#FFFFFF",
}

BRANDS: dict[str, dict[str, str]] = {"kafka": KAFKA}


def brand_palette(analysis: dict[str, Any]) -> dict[str, str]:
    """Colour overrides for the system the analysis is about (by its repository name)."""
    repo = str(analysis.get("system", {}).get("repo", "")).lower().rstrip("/")
    name = repo.rsplit("/", 1)[-1].removesuffix(".git")
    return BRANDS.get(name, {})


def with_brand(values: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """`values` (a settings snapshot) with the system's palette laid over the channel palette."""
    over = brand_palette(analysis)
    if over:
        values["palette"] = {**values.get("palette", {}), **over}
    return values
