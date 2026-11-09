"""Contact sheet: thumbnails of chosen frames with the safe-zone overlay and a time label."""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageDraw

from mvrender.frame import RenderContext, render_frame
from mvrender.layout import H, W

OVERLAY = (255, 0, 200)


def build_sheet(
    ctx: RenderContext, times: Sequence[float], *, cols: int = 4, thumb_w: int = 270, overlay: bool = True
) -> Image.Image:
    thumb_h = round(H * thumb_w / W)
    rows = -(-len(times) // cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), ctx.pal.page)
    left, top, right, bottom = ctx.safe.bounds()
    k = thumb_w / W
    for i, t in enumerate(times):
        frame, _ = render_frame(ctx, t, strict=False)
        thumb = frame.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        if overlay:
            d = ImageDraw.Draw(thumb)
            d.rectangle((left * k, top * k, right * k, bottom * k), outline=OVERLAY, width=2)
            d.text((4, 4), f"{t:.1f}s", fill=OVERLAY, font=ctx.fonts.get("crumb", 14))
        sheet.paste(thumb, ((i % cols) * thumb_w, (i // cols) * thumb_h))
    return sheet
