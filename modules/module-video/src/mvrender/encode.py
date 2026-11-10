"""Chunked parallel render: frames are a pure function of time, so chunks render independently.

The frame range [0, N) is cut into chunks of `render.chunk_s * fps` frames; a process pool renders
them, each worker piping raw RGB frames into its own single-threaded x264 encoder. The chunks are
joined with `-c copy`. Fixed encoder settings make the chunks byte-identical across runs and
worker counts.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvrender.frame import RenderContext, make_context, render_frame
from mvrender.media import MediaError, count_frames, ffmpeg_or_raise
from mvrender.timing import frames as frame_count

_CTX: RenderContext | None = None


@dataclass(frozen=True, slots=True)
class EncodeSettings:
    fps: int = 60
    crf: int = 17
    preset: str = "medium"
    max_bitrate_kbps: int = 24000
    gop_s: float = 2.0
    chunk_s: float = 10.0
    workers: int = 0

    @classmethod
    def from_settings(cls, s: dict[str, Any] | None) -> EncodeSettings:
        v = (s or {}).get("video", {})
        r = (s or {}).get("render", {})
        return cls(
            fps=int(v.get("fps", 60)),
            crf=int(v.get("crf", 17)),
            preset=str(v.get("preset", "medium")),
            max_bitrate_kbps=int(v.get("max_bitrate_kbps", 24000)),
            gop_s=float(v.get("gop_s", 2)),
            chunk_s=float(r.get("chunk_s", 10)),
            workers=int(r.get("workers", 0)),
        )

    def worker_count(self) -> int:
        return self.workers or min(os.cpu_count() or 1, 8)


@dataclass(frozen=True, slots=True)
class RenderStats:
    frames: int
    chunks: int
    workers: int
    wall_s: float
    video_s: float

    @property
    def seconds_per_video_second(self) -> float:
        """Render time per second of finished video (reported as a metric)."""
        return self.wall_s / self.video_s if self.video_s else 0.0


def ffmpeg_chunk_args(es: EncodeSettings, out: Path) -> list[str]:
    gop = round(es.fps * es.gop_s)
    return [
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920", "-r", str(es.fps), "-i", "-",
        "-c:v", "libx264", "-preset", es.preset, "-crf", str(es.crf), "-threads", "1",
        "-maxrate", f"{es.max_bitrate_kbps}k", "-bufsize", f"{2 * es.max_bitrate_kbps}k",
        "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-an", "-fflags", "+bitexact", "-flags:v", "+bitexact", str(out),
    ]  # fmt: skip


def _init_worker(
    resolved: dict[str, Any],
    fonts_dir: str,
    settings: dict[str, Any] | None,
    fps: int,
    reading_wps: float | None,
) -> None:
    """Each worker builds the same context as the parent; with another reading speed its scenes
    would start at other times than the frame count and the sound assume."""
    global _CTX
    _CTX = make_context(
        resolved, fonts_dir, settings, **({"reading_wps": reading_wps} if reading_wps else {}), fps=fps
    )


def _render_chunk(job: tuple[int, int, int, str, EncodeSettings]) -> str:
    index, first, last, out, es = job
    ctx = _CTX
    assert ctx is not None  # noqa: S101
    proc = subprocess.Popen([ffmpeg_or_raise(), *ffmpeg_chunk_args(es, Path(out))], stdin=subprocess.PIPE)  # noqa: S603
    assert proc.stdin is not None  # noqa: S101
    try:
        for n in range(first, last):
            img, _ = render_frame(ctx, n / es.fps)
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise MediaError(f"ffmpeg failed on chunk {index}")
    return out


def render_video(
    resolved: dict[str, Any],
    out_path: str | Path,
    workdir: str | Path,
    *,
    fonts_dir: str | Path,
    settings: dict[str, Any] | None = None,
    reading_wps: float | None = None,
    limit_frames: int | None = None,
) -> RenderStats:
    """Render the silent video `out_path`; `limit_frames` renders only the first frames (tests)."""
    es = EncodeSettings.from_settings(settings)
    ctx = make_context(
        resolved, fonts_dir, settings, **({"reading_wps": reading_wps} if reading_wps else {}), fps=es.fps
    )
    total_frames = ctx.timeline.frames
    n_frames = min(total_frames, limit_frames) if limit_frames else total_frames
    per = max(1, round(es.chunk_s * es.fps))
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    jobs = [
        (i, a, min(a + per, n_frames), str(work / f"chunk_{i:04d}.mp4"), es)
        for i, a in enumerate(range(0, n_frames, per))
    ]
    workers = min(es.worker_count(), len(jobs))
    t0 = time.monotonic()
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_init_worker,
        initargs=(resolved, str(fonts_dir), settings, es.fps, reading_wps),
    ) as pool:
        chunks = list(pool.map(_render_chunk, jobs))
    listing = work / "chunks.txt"
    listing.write_text("".join(f"file '{Path(c).resolve()}'\n" for c in chunks))
    p = subprocess.run(  # noqa: S603
        [ffmpeg_or_raise(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", "-fflags", "+bitexact", "-movflags", "+faststart", str(out_path)],
        capture_output=True, check=False,
    )  # fmt: skip
    if p.returncode != 0:
        raise MediaError(f"concat failed: {p.stderr[-300:]!r}")
    wall = time.monotonic() - t0
    got = count_frames(out_path)
    if got != n_frames:
        raise MediaError(f"frame count {got} != expected {n_frames}")
    return RenderStats(n_frames, len(chunks), workers, wall, n_frames / es.fps)


__all__ = ["EncodeSettings", "RenderStats", "frame_count", "render_video"]
