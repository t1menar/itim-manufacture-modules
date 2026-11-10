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


def _leveled(wav: Path, out: Path, lufs: float, ceiling: float) -> None:
    """Bring the sound to `lufs` under a brick-wall limiter with a sample-peak `ceiling` (dBFS).

    Sparse effects cannot reach -14 LUFS by a linear gain (the peaks hit the ceiling first), so the
    gain is applied before a limiter and refined by measuring the result (up to ten rounds). The gain
    never grows more than 10 dB past the first guess: past that the limiter only distorts. When the
    ceiling makes the target unreachable the closest attempt stays. (`loudnorm` in linear mode refuses
    gains that clip, so the first guess comes from a plain ebur128 measurement."""
    lim = 10 ** (ceiling / 20)
    gain = lufs - ebur128(wav).integrated
    top = gain + 10
    for _ in range(10):
        af = f"volume={gain:.3f}dB,alimiter=limit={lim:.4f}:attack=5:release=50:level=0"
        p = run(["-y", "-i", str(wav), "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)])
        if p.returncode != 0:
            raise MediaError(f"leveling failed: {p.stderr[-300:]!r}")
        err = lufs - ebur128(out).integrated
        if abs(err) <= 0.05:
            return
        gain = min(gain + err * 1.3, top)


def mux_final(
    silent: str | Path, wav: str | Path, out: str | Path, audio: AudioSettings | None = None
) -> Loudness:
    """Level the sound, mux it with the copied video, and verify the final file with ebur128.

    The AAC encode of a sparse sound is lossy in both ways: it loses up to 1 LU and its true peak
    lands up to 3 dB above the limiter ceiling, differently on every attempt. So the loop is closed
    around the encoded file: the loudness aim moves by the measured miss and the ceiling drops by the
    measured overshoot, until the file meets both targets (up to 10 rounds)."""
    audio = audio or AudioSettings()
    leveled = Path(str(out) + ".leveled.wav")
    aim = audio.lufs + 0.2
    ceiling = audio.true_peak - 0.5
    got = Loudness(0.0, 0.0, 0.0)
    for _ in range(10):
        _leveled(Path(wav), leveled, aim, ceiling)
        p = run(["-y", "-i", str(silent), "-i", str(leveled), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                 "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", f"{audio.bitrate_kbps}k", "-shortest",
                 "-movflags", "+faststart", str(out)])  # fmt: skip
        leveled.unlink(missing_ok=True)
        if p.returncode != 0:
            raise MediaError(f"mux failed: {p.stderr[-300:]!r}")
        got = ebur128(out)
        miss = audio.lufs - got.integrated
        over = got.true_peak - audio.true_peak
        if abs(miss) <= audio.tolerance_lu and over <= 0:
            return got
        aim += miss * 0.8
        if over > -0.3:
            ceiling -= over + 0.3
    raise LoudnessError(
        f"loudness {got.integrated:.1f} LUFS, true peak {got.true_peak:.1f} dBTP misses the target"
    )


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
