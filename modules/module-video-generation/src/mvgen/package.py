"""Final file: level and mux the sound, cover frame, technical checks and the post text."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvrender.frame import RenderContext
from mvrender.media import count_frames, probe
from mvrender.package import AudioSettings, LoudnessError, extract_cover, mux_final

from mvgen.errors import CheckFailed
from mvgen.post import build_metadata, render_post, source_label
from mvgen.settings import Limits


@dataclass(slots=True)
class Packaged:
    final: Path
    cover: Path
    post: dict[str, Any]  # {caption, hashtags}
    metadata: dict[str, Any]
    checks: dict[str, Any]
    video: dict[str, Any]


def cover_time(script: dict[str, Any], timeline: dict[str, Any]) -> float:
    """`meta.cover`: a mark of the timeline (`{scene, at:{at: mark}}`) or the start of its scene."""
    cover = script["meta"].get("cover") or {}
    at = cover.get("at")
    mark = at.get("at") if isinstance(at, dict) else None
    if mark and mark in timeline["marks"]:
        return float(timeline["marks"][mark])
    for sc in timeline["scenes"]:
        if sc["id"] == cover.get("scene"):
            return float(sc["start"])
    return 2.4


def post_text(
    post: dict[str, Any],
    capture: dict[str, Any],
    system: dict[str, Any] | None,
    limits: Limits,
    channel: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    values = {k: str(v["value"]) for k, v in capture["values"].items()}
    source = source_label(system["repo"], system["ref"]) if system else ""
    return render_post(
        post, values, template=channel.get("caption_template"), channel_hashtags=list(channel.get("hashtags") or []),
        source=source, max_caption_chars=limits.max_caption_chars, max_hashtags=limits.max_hashtags,
    )  # fmt: skip


def package(
    script: dict[str, Any],
    post: dict[str, Any],
    capture: dict[str, Any],
    system: dict[str, Any] | None,
    channel: dict[str, Any],
    silent: Path,
    sound: Path,
    rctx: RenderContext,
    timeline: dict[str, Any],
    workdir: Path,
    values: dict[str, Any],
    limits: Limits,
) -> Packaged:
    rendered, problems = post_text(post, capture, system, limits, channel)
    if problems:
        raise CheckFailed("post_limits", "; ".join(problems), {"post_limits": {"status": "fail", "value": problems}})
    audio = AudioSettings.from_settings(values)
    final = workdir / "final.mp4"
    try:
        loud = mux_final(silent, sound, final, audio)
    except LoudnessError as exc:
        raise CheckFailed("loudness", str(exc), {"loudness": {"status": "fail", "value": str(exc)}}) from exc
    cover = workdir / "cover.jpg"
    extract_cover(rctx, cover_time(script, timeline), cover, 90)
    info = probe(final)
    frames = count_frames(final)
    size_mb = final.stat().st_size / 1e6
    vs: dict[str, Any] = values.get("video") or {}
    want = (int(vs.get("width", 1080)), int(vs.get("height", 1920)), float(vs.get("fps", 60)))
    checks: dict[str, Any] = {
        "loudness": {
            "status": "pass",
            "value": {"lufs": loud.integrated, "true_peak": loud.true_peak},
            "limit": f"{audio.lufs}±{audio.tolerance_lu} LUFS, <= {audio.true_peak} dBTP",
        },
        "format": {
            "status": "pass" if (info.width, info.height, info.fps) == want and info.faststart
            and info.video_codec == "h264" else "fail",
            "value": f"{info.video_codec} {info.width}x{info.height}@{info.fps:g}",
            "limit": f"h264 {want[0]}x{want[1]}@{want[2]:g} faststart",
        },
        "bitrate_size": {
            "status": "pass" if size_mb <= limits.max_size_mb else "fail",
            "value": round(size_mb, 1), "limit": limits.max_size_mb,
        },
        "post_limits": {"status": "pass", "value": len(rendered["caption"]), "limit": limits.max_caption_chars},
    }  # fmt: skip
    failed = {k: v for k, v in checks.items() if v["status"] == "fail"}
    if failed:
        raise CheckFailed("package", "package checks failed: " + ", ".join(failed), failed)
    return Packaged(
        final, cover,
        {"caption": rendered["caption"], "hashtags": rendered["hashtags"]},
        build_metadata(script, rendered, post), checks,
        {"duration_s": round(frames / info.fps, 3), "size": final.stat().st_size,
         "width": info.width, "height": info.height, "fps": int(info.fps)},
    )  # fmt: skip
