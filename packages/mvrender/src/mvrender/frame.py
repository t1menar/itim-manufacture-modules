"""One frame of the video: `render_frame(ctx, T)`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from mvrender import timing as tm
from mvrender.draw.canvas import Canvas, Record
from mvrender.draw.captions import draw_caption, draw_notes, ramp
from mvrender.draw.debugger import draw_debugger
from mvrender.draw.diagram import draw_diagram
from mvrender.draw.terminal import draw_terminal
from mvrender.draw.title import draw_title
from mvrender.fonts import FontSet, fonts_in
from mvrender.layout import MID, PANEL, Geometry, H, W, geometry
from mvrender.palette import Palette
from mvrender.safezone import SafeRect, to_reels
from mvrender.timeline import Timeline
from mvrender.timeline import build as build_timeline


@dataclass
class RenderContext:
    resolved: dict[str, Any]
    timeline: Timeline
    fonts: FontSet
    pal: Palette
    timing: tm.Timing
    geo: Geometry
    safe: SafeRect = field(default_factory=SafeRect)
    _bg: dict[bool, Image.Image] = field(default_factory=dict)

    @property
    def ref_name(self) -> str:
        return str(self.resolved["meta"]["system"]["ref"])

    @property
    def captures(self) -> dict[str, str]:
        return dict(self.resolved.get("captures", {}))


def make_context(
    resolved: dict[str, Any],
    fonts_dir: str | Path | None = None,
    settings: dict[str, Any] | None = None,
    reading_wps: float = tm.DEFAULT_READING_WPS,
    fps: int = 60,
) -> RenderContext:
    s = settings or {}
    timing = tm.Timing.from_settings(s.get("timing"))
    fonts = fonts_in(str(fonts_dir)) if fonts_dir else fonts_in(str(FontSet().directory))
    safe_zone = s.get("video", {}).get("safe_zone", {})
    return RenderContext(
        resolved,
        build_timeline(resolved, timing, reading_wps, fps),
        fonts,
        Palette(s.get("palette")),
        timing,
        geometry(fonts),
        SafeRect(**{k: int(v) for k, v in safe_zone.items()}) if safe_zone else SafeRect(),
    )


def _background(ctx: RenderContext, with_panel: bool) -> Image.Image:
    if with_panel not in ctx._bg:
        bg = Image.new("RGB", (W, H), ctx.pal.page)
        from PIL import ImageDraw

        sh = Image.new("L", (W, H), 0)
        sd = ImageDraw.Draw(sh)
        sd.rounded_rectangle((MID[0] + 6, MID[1] + 18, MID[2] - 6, MID[3] + 18), radius=24, fill=60)
        if with_panel:
            sd.rounded_rectangle(
                (PANEL[0] + 6, PANEL[1] + 14, PANEL[2] - 6, PANEL[3] + 14), radius=24, fill=34
            )
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        bg.paste(Image.new("RGB", (W, H), (120, 85, 50)), (0, 0), sh)
        ctx._bg[with_panel] = bg
    return ctx._bg[with_panel]


def render_frame(ctx: RenderContext, T: float, *, strict: bool = True) -> tuple[Image.Image, list[Record]]:
    """Render absolute time `T`; returns the image and the text records for the glyph check."""
    tl = ctx.timeline
    idx, t = tl.locate(T)
    scene = ctx.resolved["scenes"][idx]
    st = tl.scenes[idx]
    has_panel = bool(scene.get("panel"))
    img = _background(ctx, has_panel).copy()
    cv = Canvas(img, ctx.fonts, ctx.pal, scene=scene["id"], safe=ctx.safe, strict=strict)

    draw_caption(cv, scene, st, t, first_scene=idx == 0)
    if idx != 0:
        draw_notes(cv, st.notes, t)

    kind = scene["kind"]
    if kind == "terminal" and st.terminal:
        draw_terminal(cv, st.terminal, scene["terminal"].get("title", ""), t, T, ctx.geo)
    elif kind == "debugger" and st.terminal:
        enter = st.debugger_enter or 0.0
        resume = st.debugger_resume or 1e9
        if enter <= t < resume:
            draw_debugger(cv, scene, st, t, ctx.timing, ctx.geo, ctx.captures, ctx.ref_name)
        else:
            draw_terminal(cv, st.terminal, scene["terminal"].get("title", ""), t, T, ctx.geo)
    elif kind == "title":
        draw_title(cv, scene["title"], t)
    elif kind == "diagram":
        draw_diagram(cv, scene["diagram"], MID, scene, st, t, ctx.timing, ctx.ref_name, ctx.captures)
    if has_panel:
        draw_diagram(cv, scene["panel"], PANEL, scene, st, t, ctx.timing, ctx.ref_name, ctx.captures)

    out = to_reels(img, ctx.pal.page, ctx.pal.grid)
    fade = (
        1 - ramp(T, 0, 0.3) if T < 0.3 else (ramp(T, tl.total_s - 0.4, 0.4) if tl.total_s - 0.4 < T else 0.0)
    )
    if fade > 0:
        out = Image.blend(out, Image.new("RGB", (W, H), ctx.pal.page), fade)
    return out, cv.records
