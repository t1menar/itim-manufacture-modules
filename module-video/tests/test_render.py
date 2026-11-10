from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from mvideo.settings_model import DEFAULT_PALETTE
from mvrender import palette as palette_mod
from mvrender.draw.canvas import SafeZoneError
from mvrender.fonts import FontSet, GlyphMissing
from mvrender.frame import RenderContext, make_context, render_frame
from mvrender.resolve import CaptureMissing, ExpectMismatch, SourceMissing, resolve
from mvrender.sheet import build_sheet
from tests import refdata

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "fonts"
SOURCES = refdata.REFERENCE / "sources"
APPROVED = Path(__file__).parent / "approved"
PREVIEW_TIMES = (2, 12, 40, 70, 110, 140)


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def line(self, path: str, n: int) -> str | None:
        lines = (self.root / path).read_text(encoding="utf-8").split("\n")
        return lines[n - 1] if 1 <= n <= len(lines) else None


def resolved_reference(script: dict[str, Any] | None = None) -> dict[str, Any]:
    return resolve(script or refdata.load("script.en.json"), refdata.load("capture.json"), Tree(SOURCES))


@pytest.fixture(scope="module")
def ctx() -> RenderContext:
    return make_context(resolved_reference(), FONTS)


def ssim(a: Image.Image, b: Image.Image, win: int = 8) -> float:
    """Mean structural similarity of two images over non-overlapping windows (grey)."""
    x = np.asarray(a.convert("L"), dtype=np.float64)
    y = np.asarray(b.convert("L"), dtype=np.float64)
    h, w = (x.shape[0] // win) * win, (x.shape[1] // win) * win
    xb = x[:h, :w].reshape(h // win, win, w // win, win).swapaxes(1, 2).reshape(-1, win * win)
    yb = y[:h, :w].reshape(h // win, win, w // win, win).swapaxes(1, 2).reshape(-1, win * win)
    mx, my = xb.mean(1), yb.mean(1)
    vx, vy = xb.var(1), yb.var(1)
    cov = ((xb - mx[:, None]) * (yb - my[:, None])).mean(1)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx**2 + my**2 + c1) * (vx + vy + c2))
    return float(s.mean())


# ---- previews ----------------------------------------------------------------------------------


@pytest.mark.parametrize("t", PREVIEW_TIMES)
def test_previews_match_the_approved_frames(ctx: RenderContext, t: int) -> None:
    img, _ = render_frame(ctx, float(t))
    assert img.size == (1080, 1920)
    path = APPROVED / f"frame_{t:03d}.png"
    if os.environ.get("CI") and not path.exists():
        pytest.fail(f"approved frame {path.name} is missing; generate it locally with UPDATE_APPROVED=1")
    if os.environ.get("UPDATE_APPROVED") or not path.exists():
        APPROVED.mkdir(exist_ok=True)
        img.save(path)
    assert ssim(img, Image.open(path)) >= 0.98


def test_ssim_detects_a_difference(ctx: RenderContext) -> None:
    a, _ = render_frame(ctx, 12.0)
    b, _ = render_frame(ctx, 40.0)
    assert ssim(a, a) == pytest.approx(1.0)
    assert ssim(a, b) < 0.98


def test_every_frame_of_the_reference_renders_without_glyph_or_safe_zone_errors(ctx: RenderContext) -> None:
    for t in range(0, int(ctx.timeline.total_s), 3):
        render_frame(ctx, float(t))  # strict: raises on a missing glyph or a box outside the safe zone


def test_frame_is_deterministic(ctx: RenderContext) -> None:
    a, _ = render_frame(ctx, 70.0)
    b, _ = render_frame(ctx, 70.0)
    assert a.tobytes() == b.tobytes()


# ---- fonts and glyphs --------------------------------------------------------------------------


def test_only_open_fonts_are_used() -> None:
    from mvrender.fonts import ROLES

    assert {r.file.split("-")[0] for r in ROLES.values()} == {"Inter", "JetBrainsMono"}
    assert (FONTS / "fonts.lock").is_file()


def test_missing_glyph_fails_with_character_codepoint_role_and_scene() -> None:
    script = copy.deepcopy(refdata.load("script.en.json"))
    scene = next(s for s in script["scenes"] if s["id"] == "s2-pg-database")
    scene["terminal"]["events"][0]["text"] = "SELECT '漢字';"
    c = make_context(resolved_reference(script), FONTS)
    idx = next(i for i, s in enumerate(c.resolved["scenes"]) if s["id"] == "s2-pg-database")
    with pytest.raises(GlyphMissing) as err:
        render_frame(c, c.timeline.starts[idx] + 6.0)
    e = err.value
    assert (e.char, e.role, e.scene) == ("漢", "term", "s2-pg-database")
    assert "U+6F22" in str(e)


def test_fontset_reports_missing_characters() -> None:
    fs = FontSet(FONTS)
    assert fs.missing("term", "abc") == []
    assert fs.missing("term", "a漢b") == ["漢"]


def test_monospace_columns_come_from_the_font_advance(ctx: RenderContext) -> None:
    adv = ctx.fonts.advance("term")
    assert ctx.geo.term_cols == int((1040 - 72 - 24) // adv)


# ---- safe zone and sheet -----------------------------------------------------------------------


def test_element_outside_the_safe_zone_fails() -> None:
    script = copy.deepcopy(refdata.load("script.en.json"))
    outro = next(s for s in script["scenes"] if s["id"] == "s9-outro")
    outro["panel"]["elements"][0]["text"] = "x" * 90  # 90 chars: wider than the card
    c = make_context(resolved_reference(script), FONTS)
    idx = next(i for i, s in enumerate(c.resolved["scenes"]) if s["id"] == "s9-outro")
    with pytest.raises(SafeZoneError) as err:
        render_frame(c, c.timeline.starts[idx] + 3.0)
    assert err.value.scene == "s9-outro"


def test_contact_sheet_shows_the_overlay(ctx: RenderContext) -> None:
    sheet = build_sheet(ctx, [12.0, 40.0, 70.0, 110.0], cols=2, thumb_w=270)
    assert sheet.size == (540, 2 * 480)
    px = np.asarray(sheet)
    red = (px[:, :, 0] > 240) & (px[:, :, 1] < 40) & (px[:, :, 2] > 150)
    assert red.sum() > 200
    plain = build_sheet(ctx, [12.0], cols=1, thumb_w=270, overlay=False)
    pp = np.asarray(plain)
    assert not ((pp[:, :, 0] > 240) & (pp[:, :, 1] < 40) & (pp[:, :, 2] > 150)).any()


# ---- resolve and timeline ----------------------------------------------------------------------


def test_resolve_fills_captures_and_source_lines() -> None:
    r = resolved_reference()
    assert r["format"] == "manufacture.resolved/1"
    step = next(
        s
        for sc in r["scenes"]
        for s in (sc.get("debugger") or {}).get("steps", [])
        if s["id"] == "s4-new-oid"
    )
    assert step["caption"][1] == "the database gets number *16384*"
    assert any("GetNewOidWithIndex" in row["text"] for row in step["rows"])
    cmd = next(
        e
        for sc in r["scenes"]
        for e in (sc.get("terminal") or {}).get("events", [])
        if e.get("cmd") == "c-ls-after"
    )
    assert cmd["rows"] == ["1", "16384", "4", "5"] and cmd["prompt"] == "$ "


def test_resolve_errors_are_typed() -> None:
    script = refdata.load("script.en.json")
    cap = refdata.load("capture.json")
    cap2 = copy.deepcopy(cap)
    del cap2["values"]["oid_shop"]
    with pytest.raises(CaptureMissing) as e1:
        resolve(script, cap2, Tree(SOURCES))
    assert e1.value.code == "capture_missing" and e1.value.name == "oid_shop"

    bad = copy.deepcopy(script)
    dbg = next(s for s in bad["scenes"] if s["kind"] == "debugger")["debugger"]
    dbg["steps"][0]["seq"][1]["expect"] = "NotOnThatLine"
    with pytest.raises(ExpectMismatch) as e2:
        resolve(bad, cap, Tree(SOURCES))
    assert e2.value.code == "expect_mismatch"

    with pytest.raises(SourceMissing):
        resolve(script, cap, Tree(ROOT / "nowhere"))


def test_timeline_json_has_marks_and_frames(ctx: RenderContext) -> None:
    tl = ctx.timeline.as_json()
    assert tl["format"] == "manufacture.timeline/1" and tl["fps"] == 60
    assert tl["frames"] == round(tl["total_s"] * 60)
    assert tl["scenes"][0]["start"] == 0 and len(tl["scenes"]) == 10
    assert "s4-create.s4-new-oid.line.1405" in tl["marks"]
    starts = [s["start"] for s in tl["scenes"]]
    assert starts == sorted(starts)


def test_palette_defaults_equal_the_settings_defaults() -> None:
    assert palette_mod.DEFAULTS == DEFAULT_PALETTE


# ---- the renderer carries no content -----------------------------------------------------------

REFERENCE_STRINGS = [
    "CREATE DATABASE", "template1", "template0", "createdb", "pg_database", "dbcommands", "bufmgr",
    "16384", "shop", "folders3", "PGDATA", "ShareLock", "WAL_LOG", "base/1", "Avenir", "SFNSMono",
]  # fmt: skip


def test_no_reference_content_remains_in_mvrender() -> None:
    offenders: list[str] = []
    for path in (ROOT / "src" / "mvrender").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.name}: {s}" for s in REFERENCE_STRINGS if s in text]
        offenders += [
            f"{path.name}: line-number literal {m}"
            for m in re.findall(r"\b(?:4813|4837|1405|1458|769)\b", text)
        ]
    assert offenders == []


def test_long_typed_command_soft_wraps_and_stays_in_the_safe_zone():
    from mvrender.draw.terminal import _break_points, wrap_segments

    line = "$ /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic orders"
    points = _break_points(line, 40)
    rows = wrap_segments([(line, (0, 0, 0))], points)
    texts = ["".join(t for t, _ in r) for r in rows]
    assert "".join(texts) == line
    assert all(len(t) <= 40 for t in texts)
    assert len(texts) == len(points) + 1 > 1
    # a prefix is cut at the same places, so the wrap does not move while the command is typed
    assert wrap_segments([(line[:50], (0, 0, 0))], points)[0][0][0] == texts[0]


def test_long_window_title_is_trimmed_to_fit_the_bar(ctx: RenderContext) -> None:
    from mvrender.draw.canvas import Canvas
    from mvrender.draw.terminal import draw_window_frame
    from mvrender.layout import MID

    path = "clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java"
    img = Image.new("RGB", (1080, 1920))
    cv = Canvas(img, ctx.fonts, ctx.pal, scene="s4-produce", safe=ctx.safe, strict=True)
    draw_window_frame(cv, MID, path)  # strict canvas: a title outside the safe zone would raise
    shown = next(r.text for r in cv.records if r.role == "window_title")
    assert shown.startswith("...") and shown.endswith("KafkaProducer.java")


def test_code_card_path_shares_the_row_with_the_ref_name(ctx: RenderContext) -> None:
    from mvrender.draw.canvas import Canvas
    from mvrender.draw.elements import code_card

    path = "storage/src/main/java/org/apache/kafka/storage/internals/checkpoint/OffsetCheckpointFile.java"
    img = Image.new("RGB", (1080, 1920))
    cv = Canvas(img, ctx.fonts, ctx.pal, scene="s8-checkpoint", safe=ctx.safe, strict=True)
    rows = [{"n": 79, "text": "public String toString() {"}, {"n": 80, "text": "}"}]
    ref = "OffsetCheckpointFile.java"
    code_card(cv, (60, 300, 1020, 700), path, rows, 79, "one line per partition", ref, 1.0)
    crumbs = [r.text for r in cv.records if r.role == "crumb" and r.text != ref]
    assert crumbs[0].startswith("...") and crumbs[0].endswith(ref)
