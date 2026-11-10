"""Everything the video depends on comes from the idea: palette, limits, design notes, instructions.

`values_from_idea` builds the settings dict that `mvrender` reads (`palette`, `video`, `audio`,
`render`, `timing`), so nothing about the look is hard-coded in the module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mvrender.timing import DEFAULT_READING_WPS

DEFAULT_DURATION = (20.0, 60.0)


@dataclass(frozen=True, slots=True)
class Limits:
    duration_min_s: float = DEFAULT_DURATION[0]
    duration_max_s: float = DEFAULT_DURATION[1]
    reading_wps: float = DEFAULT_READING_WPS
    max_cost_usd: Decimal = Decimal("1.0")
    max_caption_chars: int = 500
    max_hashtags: int = 8
    max_size_mb: float = 100.0
    capture_fix_rounds: int = 2
    glyph_sample_s: float = 2.0

    @classmethod
    def from_idea(cls, idea: Mapping[str, Any]) -> Limits:
        c: Mapping[str, Any] = idea.get("constraints") or {}
        dur: Mapping[str, Any] = c.get("duration_s") or {}
        d = cls()
        return cls(
            duration_min_s=float(dur.get("min", d.duration_min_s)),
            duration_max_s=float(dur.get("max", d.duration_max_s)),
            reading_wps=float(c.get("reading_wps", d.reading_wps)),
            max_cost_usd=Decimal(str(c.get("max_cost_usd", d.max_cost_usd))),
            max_caption_chars=int(c.get("max_caption_chars", d.max_caption_chars)),
            max_hashtags=int(c.get("max_hashtags", d.max_hashtags)),
            max_size_mb=float(c.get("max_size_mb", d.max_size_mb)),
            capture_fix_rounds=int(c.get("capture_fix_rounds", d.capture_fix_rounds)),
            glyph_sample_s=float(c.get("glyph_sample_s", d.glyph_sample_s)),
        )


def values_from_idea(idea: Mapping[str, Any], base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Settings for `mvrender`: `base` (platform defaults) with the idea's palette and video overrides on top."""
    values: dict[str, Any] = {k: dict(v) if isinstance(v, dict) else v for k, v in (base or {}).items()}
    palette = {**(values.get("palette") or {}), **(idea.get("palette") or {})}
    if palette:
        values["palette"] = palette
    c: Mapping[str, Any] = idea.get("constraints") or {}
    video = dict(values.get("video") or {})
    for key in ("fps", "crf", "preset", "max_bitrate_kbps", "width", "height"):
        if key in c:
            video[key] = c[key]
    values["video"] = video
    return values


def design_brief(idea: Mapping[str, Any]) -> dict[str, Any]:
    """What the capture and package agents are told about the look and the post: idea fields only."""
    ins: Mapping[str, Any] = idea.get("instructions") or {}
    return {
        "video_brief": idea.get("video_brief"),
        "design_notes": idea.get("design_notes"),
        "instructions": ins.get("video"),
        "must_show": idea.get("must_show") or [],
        "must_avoid": idea.get("must_avoid") or [],
    }
