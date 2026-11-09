"""Packaging: sound track, two-pass loudness, final mux and cover (03 section 4.6)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvrender import cues as cues_mod
from mvrender import sfx
from mvrender.frame import RenderContext, render_frame
from mvrender.media import (
    Loudness,
    MediaError,
    count_frames,
    ebur128,
    ffmpeg_or_raise,
    loudnorm_measure,
    probe,
    run,
)  # fmt: skip


class LoudnessError(MediaError):
    """The final file misses the loudness target."""


@dataclass(frozen=True, slots=True)
class AudioSettings:
    lufs: float = -14.0
    true_peak: float = -1.0
    lra: float = 11.0
    tolerance_lu: float = 0.5
    bitrate_kbps: int = 128
    ambient_pad: bool = True

    @classmethod
    def from_settings(cls, s: dict[str, Any] | None) -> AudioSettings:
        a = (s or {}).get("audio", {})
        return cls(
            float(a.get("lufs", -14)),
            float(a.get("true_peak", -1.0)),
            float(a.get("lra", 11)),
            float(a.get("tolerance_lu", 0.5)),
            int(a.get("bitrate_kbps", 128)),
            bool(a.get("ambient_pad", True)),
        )


def render_sound(
    ctx: RenderContext, out_wav: str | Path, audio: AudioSettings | None = None
) -> list[cues_mod.Cue]:
    """Synthesize the cue track (`sfx.en.wav`); returns the cues used."""
    audio = audio or AudioSettings()
    events = cues_mod.animation_events(ctx.resolved, ctx.timeline, ctx.timing)
    cues = cues_mod.from_events(events)
    problems = cues_mod.check_cues_match(cues, events, ctx.timeline.fps)
    if problems:
        raise MediaError("cues_match_animations: " + "; ".join(problems[:5]))
    sfx.write_wav(out_wav, sfx.synthesize(cues, ctx.timeline.total_s, ambient=audio.ambient_pad))
    return cues


def _leveled(wav: Path, out: Path, audio: AudioSettings) -> None:
    """Bring the sound to the target loudness under the true-peak ceiling.

    Sparse effects cannot reach -14 LUFS by a linear gain (the peaks hit the ceiling first), so
    the gain is applied before a brick-wall limiter and refined by measuring the result
    (up to six rounds). `loudnorm` in linear mode refuses gains that clip, which is why it is
    only used to measure.
    """
    margin = 0.5  # headroom for the AAC encoder's overshoot
    ceiling = audio.true_peak - margin  # sample-peak ceiling of the limiter, adapted below
    gain = audio.lufs - float(loudnorm_measure(wav, audio.lufs, audio.true_peak, audio.lra)["input_i"])
    got = Loudness(0.0, 0.0, 0.0)
    for _ in range(10):
        lim = 10 ** (ceiling / 20)
        af = f"volume={gain:.3f}dB,alimiter=limit={lim:.4f}:attack=5:release=50:level=0"
        p = run(["-y", "-i", str(wav), "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)])
        if p.returncode != 0:
            raise MediaError(f"leveling failed: {p.stderr[-300:]!r}")
        got = ebur128(out)
        err = audio.lufs - got.integrated
        over = got.true_peak - (audio.true_peak - margin)
        if abs(err) <= audio.tolerance_lu / 2 and over <= 0.1:
            return
        if over > 0.1:  # inter-sample peaks above the limiter ceiling: lower the ceiling
            ceiling -= over
        gain += err * 1.3
    raise LoudnessError(
        f"cannot reach {audio.lufs} LUFS under {audio.true_peak} dBTP "
        f"(got {got.integrated:.1f}, {got.true_peak:.1f})"
    )


def mux_final(
    silent: str | Path, wav: str | Path, out: str | Path, audio: AudioSettings | None = None
) -> Loudness:
    """Level the sound, mux it with the copied video, and verify the final file with ebur128."""
    audio = audio or AudioSettings()
    leveled = Path(str(out) + ".leveled.wav")
    _leveled(Path(wav), leveled, audio)
    p = run(["-y", "-i", str(silent), "-i", str(leveled), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", f"{audio.bitrate_kbps}k", "-shortest",
             "-movflags", "+faststart", str(out)])  # fmt: skip
    leveled.unlink(missing_ok=True)
    if p.returncode != 0:
        raise MediaError(f"mux failed: {p.stderr[-300:]!r}")
    got = ebur128(out)
    if abs(got.integrated - audio.lufs) > audio.tolerance_lu or got.true_peak > audio.true_peak:
        raise LoudnessError(
            f"loudness {got.integrated:.1f} LUFS, true peak {got.true_peak:.1f} dBTP misses the target"
        )
    return got


def extract_cover(ctx: RenderContext, t: float, out: str | Path, quality: int = 92) -> None:
    """Cover image: the frame at time `t` as JPEG."""
    img, _ = render_frame(ctx, t)
    img.save(out, "JPEG", quality=quality)


def verify_frames(path: str | Path, expected: int) -> None:
    got = count_frames(path)
    if got != expected:
        raise MediaError(f"frames: {got} != {expected}")


__all__ = [
    "AudioSettings",
    "LoudnessError",
    "extract_cover",
    "ffmpeg_or_raise",
    "mux_final",
    "probe",
    "render_sound",
    "verify_frames",
]
