"""B5: cues, sound, chunked encode determinism, frame count and loudness."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest

from mvrender import cues as cues_mod
from mvrender import media, sfx
from mvrender.encode import render_video
from mvrender.frame import make_context
from mvrender.package import AudioSettings, mux_final, render_sound
from test_render import FONTS, resolved_reference

needs_ffmpeg = pytest.mark.skipif(media.find_ffmpeg() is None, reason="ffmpeg not available")

SETTINGS = {"render": {"chunk_s": 1.0}, "video": {"preset": "ultrafast"}}


@pytest.fixture(scope="module")
def ctx():  # type: ignore[no-untyped-def]
    return make_context(resolved_reference(), FONTS)


def test_cues_match_animations(ctx) -> None:  # type: ignore[no-untyped-def]
    events = cues_mod.animation_events(ctx.resolved, ctx.timeline, ctx.timing)
    cues = cues_mod.from_events(events)
    assert len(events) > 100
    assert cues_mod.check_cues_match(cues, events, ctx.timeline.fps) == []


def test_cues_match_fails_when_a_cue_is_removed(ctx) -> None:  # type: ignore[no-untyped-def]
    events = cues_mod.animation_events(ctx.resolved, ctx.timeline, ctx.timing)
    cues = cues_mod.from_events(events)
    assert cues_mod.check_cues_match(cues[:5] + cues[6:], events, ctx.timeline.fps)
    shifted = copy.copy(cues[10])
    assert cues_mod.check_cues_match(
        [*cues[:10], cues_mod.Cue(shifted.t + 0.2, shifted.kind, shifted.p, shifted.event), *cues[11:]],
        events,
        ctx.timeline.fps,
    )


def test_sfx_is_deterministic_and_limited(ctx) -> None:  # type: ignore[no-untyped-def]
    events = cues_mod.animation_events(ctx.resolved, ctx.timeline, ctx.timing)
    cues = cues_mod.from_events(events)[:60]
    a = sfx.synthesize(cues, 20.0)
    b = sfx.synthesize(cues, 20.0)
    assert a.shape == (20 * sfx.SR, 2) and a.dtype == np.int16
    assert np.array_equal(a, b)
    peak = np.abs(a).max() / 32768
    assert 0.5 < peak < 0.95


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@needs_ffmpeg
def test_workers_give_identical_bytes_and_frame_count(tmp_path: Path) -> None:
    resolved = resolved_reference()
    hashes = set()
    for w in (1, 4, 8):
        s = {**SETTINGS, "render": {"chunk_s": 1.0, "workers": w}}
        out = tmp_path / f"v{w}.mp4"
        stats = render_video(resolved, out, tmp_path / f"w{w}", fonts_dir=FONTS, settings=s, limit_frames=150)
        assert stats.frames == 150
        assert media.count_frames(out) == 150
        hashes.add(sha(out))
    assert len(hashes) == 1


@needs_ffmpeg
def test_stream_properties(tmp_path: Path) -> None:
    out = tmp_path / "v.mp4"
    render_video(
        resolved_reference(), out, tmp_path / "w", fonts_dir=FONTS, settings=SETTINGS, limit_frames=120
    )
    info = media.probe(out)
    assert (info.width, info.height, info.fps) == (1080, 1920, 60)
    assert info.faststart


@needs_ffmpeg
def test_mux_reaches_loudness_target(ctx, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cues = cues_mod.from_events(cues_mod.animation_events(ctx.resolved, ctx.timeline, ctx.timing))
    cues = [c for c in cues if c.t < 30]
    wav = tmp_path / "s.wav"
    sfx.write_wav(wav, sfx.synthesize(cues, 30.0))
    silent = tmp_path / "silent.mp4"
    render_video(
        ctx.resolved, silent, tmp_path / "w", fonts_dir=FONTS, settings=SETTINGS, limit_frames=60 * 30
    )
    got = mux_final(silent, wav, tmp_path / "final.mp4", AudioSettings())
    assert abs(got.integrated + 14) <= 0.5
    assert got.true_peak <= -1.0


def test_render_sound_helper(ctx, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    cues = render_sound(ctx, tmp_path / "a.wav")
    assert cues and (tmp_path / "a.wav").stat().st_size > 1_000_000


def test_worker_context_uses_the_parent_reading_speed() -> None:
    """The picture's scenes must start when the sound and the frame count assume (reading speed 3.0)."""
    from mvrender import encode

    resolved = resolved_reference()
    encode._init_worker(resolved, FONTS, None, 30, 3.0)
    parent = make_context(resolved, FONTS, None, reading_wps=3.0, fps=30)
    assert encode._CTX is not None
    assert encode._CTX.timeline.starts == parent.timeline.starts
    assert encode._CTX.timeline.starts != make_context(resolved, FONTS, None, fps=30).timeline.starts
