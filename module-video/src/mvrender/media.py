"""ffmpeg access and small probes (frame count, stream format, loudness)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(Exception):
    pass


def find_ffmpeg() -> str | None:
    """`$FFMPEG`, then `ffmpeg` on PATH, then the static binary of `imageio-ffmpeg` (dev machines)."""
    env = os.environ.get("FFMPEG")
    if env:
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None


def ffmpeg_or_raise() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise MediaError("ffmpeg not found: install it, put it on PATH or set FFMPEG")
    return exe


def run(args: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603
        [ffmpeg_or_raise(), "-hide_banner", "-nostdin", *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def count_frames(path: str | Path) -> int:
    """Video frames in the file, counted by reading the stream (no decoding)."""
    p = run(["-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"])
    m = re.findall(rb"frame=\s*(\d+)", p.stderr)
    if not m:
        raise MediaError(f"cannot count frames of {path}: {p.stderr[-300:]!r}")
    return int(m[-1])


@dataclass(frozen=True, slots=True)
class StreamInfo:
    video_codec: str
    profile: str
    pix_fmt: str
    width: int
    height: int
    fps: float
    audio_codec: str
    sample_rate: int
    channels: str
    faststart: bool
    size: int


def probe(path: str | Path) -> StreamInfo:
    p = run(["-i", str(path)])
    text = p.stderr.decode("utf-8", "replace")
    line = next((ln for ln in text.splitlines() if "Video:" in ln), "")
    v = re.search(r"Video: (\w+)(?: \(([^)]*)\))?", line)
    pix = re.search(r"Video: [^,]*, (\w+)", line)
    size = re.search(r", (\d+)x(\d+)", line)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", line)
    a = re.search(r"Audio: (\w+)[^,]*, (\d+) Hz, (\w+)", text)
    if not (v and pix and size and fps):
        raise MediaError(f"no video stream in {path}")
    raw = Path(path).read_bytes()[: 4096 * 64]
    moov, mdat = raw.find(b"moov"), raw.find(b"mdat")
    return StreamInfo(
        v.group(1),
        v.group(2) or "",
        pix.group(1),
        int(size.group(1)),
        int(size.group(2)),
        float(fps.group(1)),
        a.group(1) if a else "",
        int(a.group(2)) if a else 0,
        a.group(3) if a else "",
        moov != -1 and (mdat == -1 or moov < mdat),
        Path(path).stat().st_size,
    )


@dataclass(frozen=True, slots=True)
class Loudness:
    integrated: float
    true_peak: float
    lra: float


def ebur128(path: str | Path) -> Loudness:
    """Integrated loudness (LUFS), true peak (dBTP) and loudness range of the audio stream."""
    p = run(["-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"])
    text = p.stderr.decode("utf-8", "replace")
    tail = text[text.rfind("Summary:") :]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    lra = re.search(r"LRA:\s+(-?[\d.]+) LU", tail)
    if not (i and tp and lra):
        raise MediaError(f"cannot read ebur128 summary of {path}")
    return Loudness(float(i.group(1)), float(tp.group(1)), float(lra.group(1)))


def loudnorm_measure(path: str | Path, i: float, tp: float, lra: float) -> dict[str, str]:
    """First loudnorm pass: measured values to feed the second pass."""
    p = run(
        ["-i", str(path), "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"]
    )
    text = p.stderr.decode("utf-8", "replace")
    start = text.rfind("{")
    if start < 0:
        raise MediaError("loudnorm printed no measurement")
    data: dict[str, str] = json.loads(text[start : text.rfind("}") + 1])
    return data
