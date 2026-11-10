"""Deterministic render: resolve the script against the capture, check, draw frames, synthesize the sound."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvrender.draw.canvas import SafeZoneError
from mvrender.encode import render_video
from mvrender.fonts import DEFAULT_DIR, GlyphMissing
from mvrender.frame import RenderContext, make_context, render_frame
from mvrender.media import MediaError
from mvrender.package import AudioSettings, render_sound
from mvrender.resolve import ResolveError, SourceTree, resolve
from mvrender.sheet import build_sheet

from mvgen.errors import CheckFailed
from mvgen.settings import Limits


@dataclass(slots=True)
class RenderOutput:
    silent: Path
    sound: Path
    sheet: Path
    resolved: dict[str, Any]
    timeline: dict[str, Any]
    checks: dict[str, Any]
    ctx: RenderContext


def check_duration(total: float, limits: Limits) -> dict[str, Any]:
    lo, hi = limits.duration_min_s, limits.duration_max_s
    return {
        "status": "pass" if lo <= total <= hi else "fail",
        "value": round(total, 2),
        "limit": f"{lo:g}-{hi:g}",
    }


def sample_frames(rctx: RenderContext, step_s: float, limit_s: float, checks: dict[str, Any]) -> None:
    """Strict canvas every `step_s`: a missing glyph or a safe-zone breach is a failed check."""
    t = 0.0
    last = min(rctx.timeline.total_s, limit_s)
    try:
        while t < last:
            render_frame(rctx, t, strict=True)
            t += max(step_s, 0.05)
    except GlyphMissing as exc:
        checks["glyphs"] = {"status": "fail", "value": str(exc), "limit": 0}
        raise CheckFailed("glyphs", f"glyph check: {exc}", checks) from exc
    except SafeZoneError as exc:
        checks["safe_zone"] = {"status": "fail", "value": str(exc), "limit": 0}
        raise CheckFailed("safe_zone", f"safe zone: {exc}", checks) from exc
    checks["glyphs"] = {"status": "pass", "value": 0, "limit": 0}
    checks["safe_zone"] = {"status": "pass", "value": 0, "limit": 0}


def render(
    script: dict[str, Any],
    capture: dict[str, Any],
    source: SourceTree,
    workdir: Path,
    values: dict[str, Any],
    limits: Limits,
    *,
    fonts_dir: str | Path | None = None,
    limit_frames: int | None = None,
) -> RenderOutput:
    """Blocking; the service runs it in a thread. `limit_frames` renders only the first frames (tests)."""
    fonts = str(fonts_dir or DEFAULT_DIR)
    fps = int((values.get("video") or {}).get("fps", 60))
    try:
        resolved = resolve(script, capture, source)
        rctx = make_context(resolved, fonts, values, reading_wps=limits.reading_wps, fps=fps)
    except ResolveError as exc:
        raise CheckFailed("resolve", str(exc)) from exc
    total = rctx.timeline.total_s
    checks: dict[str, Any] = {"duration": check_duration(total, limits)}
    if checks["duration"]["status"] == "fail":
        raise CheckFailed("duration", f"duration {total:.1f} s outside {checks['duration']['limit']} s", checks)
    sample_frames(rctx, limits.glyph_sample_s, (limit_frames or 10**9) / rctx.timeline.fps, checks)
    workdir.mkdir(parents=True, exist_ok=True)
    silent = workdir / "video.silent.mp4"
    stats = render_video(
        resolved, silent, workdir / "chunks", fonts_dir=fonts, settings=values,
        reading_wps=limits.reading_wps, limit_frames=limit_frames,
    )  # fmt: skip
    expected = min(rctx.timeline.frames, limit_frames or rctx.timeline.frames)
    checks["frames"] = {
        "status": "pass" if stats.frames == expected else "fail",
        "value": stats.frames,
        "limit": expected,
    }
    if checks["frames"]["status"] == "fail":
        raise CheckFailed("frames", f"rendered {stats.frames} frames, expected {expected}", checks)
    wav = workdir / "sfx.wav"
    try:
        cues = render_sound(rctx, wav, AudioSettings.from_settings(values))
    except MediaError as exc:
        checks["cues_match_animations"] = {"status": "fail", "value": str(exc), "limit": "all"}
        raise CheckFailed("cues", str(exc), checks) from exc
    checks["cues_match_animations"] = {"status": "pass", "value": len(cues), "limit": "all"}
    times = [s + 0.6 * sc.duration for s, sc in zip(rctx.timeline.starts, rctx.timeline.scenes, strict=True)]
    sheet = workdir / "sheet.jpg"
    img = build_sheet(rctx, times, cols=3, thumb_w=360, overlay=False)
    img.convert("RGB").save(sheet, "JPEG", quality=88)
    return RenderOutput(silent, wav, sheet, resolved, rctx.timeline.as_json(), checks, rctx)
