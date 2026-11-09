"""Steps capture, render and package (05 sections 2.5 to 2.7) and the real result builder."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any

from mvideo.pipeline.context import RunContext
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.agent_step import (
    RESUME_PROMPT,
    AgentStep,
    channel_json,
    common_values,
    jdump,
    reading_wps,
)
from mvideo.pipeline.steps.base import Step
from mvideo.post import build_metadata, render_post, source_label
from mvideo.sandbox.executor import CaptureFailure, ScratchSandbox, check_values, run_capture
from mvideo.storage import Artifact
from mvideo.validate.issues import Issue
from mvideo.validate.source import DirSource
from mvrender.draw.canvas import SafeZoneError
from mvrender.encode import render_video
from mvrender.fonts import DEFAULT_DIR, GlyphMissing
from mvrender.frame import make_context, render_frame
from mvrender.media import MediaError, count_frames, probe
from mvrender.package import AudioSettings, LoudnessError, extract_cover, mux_final, render_sound
from mvrender.resolve import ResolveError, resolve
from mvrender.sheet import build_sheet


def LOUD_FAIL(exc: Exception) -> dict[str, Any]:
    return {"checks": {"loudness": {"status": "fail", "value": str(exc)}}}


class CaptureStep(AgentStep):
    name = "capture"
    lo, hi = 35, 45
    produces = ("capture.plan.json",)
    settings_keys = ("sandbox_images", "sandbox", "prompt_versions", "limits")

    async def inputs(self, ctx: RunContext) -> dict[str, bytes]:
        get = ctx.storage.get_bytes
        a = await self.read_json(ctx, "analysis", "analysis.json")
        img = ctx.settings.sandbox_images[a["sandbox_image"]]
        return {
            "script.en.json": await get(ctx.outputs["script"]["script.en.json"].ref),
            "research.json": await get(ctx.outputs["research"]["research.json"].ref),
            "image.json": jdump(
                {
                    "key": a["sandbox_image"],
                    "version_expect": img.version_expect,
                    "description": img.description,
                    "sessions": {k: v.model_dump(exclude_none=True) for k, v in img.sessions.items()},
                }
            ),
        }

    async def values(self, ctx: RunContext) -> dict[str, Any]:
        a = await self.read_json(ctx, "analysis", "analysis.json")
        img = ctx.settings.sandbox_images[a["sandbox_image"]]
        return {
            "image_key": a["sandbox_image"],
            "version_expect": img.version_expect,
            "session_kinds": ", ".join(sorted({s.kind or k for k, s in img.sessions.items()})),
        }

    async def run(self, ctx: RunContext) -> dict[str, Artifact]:
        inputs = await self.inputs(ctx)
        req = self.request(ctx, inputs, await self.values(ctx))
        token = None
        if ctx.scratch is not None:
            image_key = (await self.read_json(ctx, "analysis", "analysis.json"))["sandbox_image"]

            async def make_scratch(step_id: str) -> Any:
                return ScratchSandbox(ctx.docker, ctx.settings, image_key, step_id)

            token = ctx.scratch.register(req.step_id, make_scratch)
        if token:
            req.sandbox_mcp = {"url": ctx.sandbox_mcp_url, "token": token}
        script = json.loads(inputs["script.en.json"])
        rounds = ctx.settings.limits.fix_rounds
        try:
            for attempt in range(rounds + 1):
                res, out = await self.agent_loop(ctx, req, inputs)
                plan = json.loads(out["capture.plan.json"])
                problems: list[str] = []
                log = ""
                try:
                    capture, log = await asyncio.to_thread(
                        run_capture, ctx.docker, ctx.settings, plan, script, run_id=req.step_id
                    )
                    problems = check_values(capture)
                except CaptureFailure as exc:
                    if exc.code == "version_mismatch":
                        raise StepError("blocked", "version_mismatch", str(exc), step=self.name) from exc
                    problems, log = [str(exc)], exc.log
                if not problems:
                    break
                if attempt == rounds:
                    raise StepError(
                        "blocked",
                        "not_reproducible",
                        "the capture plan could not be reproduced",
                        step=self.name,
                        details={"problems": problems[:10]},
                    )
                inputs = {
                    **inputs,
                    "execution_log.txt": log.encode(),
                    "validation_errors.json": jdump(problems),
                }
                req = dataclasses.replace(
                    req,
                    workspace=dataclasses.replace(req.workspace, inputs=inputs),
                    resume=res.result.get("session_id"),
                    prompt=RESUME_PROMPT.format(files="capture.plan.json")
                    + " The execution log is /in/execution_log.txt.",
                )
        finally:
            if token:
                await ctx.scratch.end(token)
        files = {
            "capture.plan.json": jdump(plan),
            "capture.json": jdump(capture),
            "capture.log": log.encode(),
        }
        return await self.upload(ctx, files)


async def fetch_source_tree(
    ctx: RunContext, script: dict[str, Any], analysis: dict[str, Any], dest: Path
) -> Any:
    """A SourceTree for the renderer: `ctx.source` when given, else the files of the pinned checkout."""
    if ctx.source is not None:
        return ctx.source
    research = await ctx.storage.get_bytes(ctx.outputs["research"]["research.json"].ref)
    volume = await ctx.git_cache.ensure(
        ctx.settings, analysis["system"]["repo"], json.loads(research)["commit"]
    )
    await ctx.git_cache.fetch_files(volume, sorted(set(script["sources"].values())), dest)
    return DirSource(dest)


class RenderStep(Step):
    name = "render"
    lo, hi = 45, 90
    uses_agent = False
    settings_keys = ("video", "audio", "text", "timing", "palette", "render", "fonts")

    def __init__(self, *, limit_frames: int | None = None, fonts_dir: str | None = None) -> None:
        self.limit_frames = limit_frames  # tests render a few seconds only
        self.fonts_dir = fonts_dir or str(DEFAULT_DIR)

    async def run(self, ctx: RunContext) -> dict[str, Artifact]:
        script = await json_of(ctx, "script", "script.en.json")
        capture = await json_of(ctx, "capture", "capture.json")
        analysis = await json_of(ctx, "analysis", "analysis.json")
        values = ctx.settings.model_dump(mode="json")
        with tempfile.TemporaryDirectory(prefix="mvideo-render-") as tmp:
            tmpd = Path(tmp)
            source = await fetch_source_tree(ctx, script, analysis, tmpd / "src")
            try:
                resolved = resolve(script, capture, source)
                rctx = make_context(
                    resolved, self.fonts_dir, values, reading_wps=reading_wps(ctx), fps=ctx.settings.video.fps
                )
            except ResolveError as exc:
                raise StepError("fatal", "check_failed", str(exc), step=self.name) from exc
            checks: dict[str, Any] = {}
            lo, hi = ctx.settings.video.duration_s.min, ctx.settings.video.duration_s.max
            total = rctx.timeline.total_s
            checks["duration"] = {
                "status": "pass" if lo <= total <= hi else "fail",
                "value": round(total, 2),
                "limit": f"{lo:g}-{hi:g}",
            }
            if checks["duration"]["status"] == "fail":
                raise StepError(
                    "fatal", "check_failed", f"duration {total:.1f} s outside {lo:g}-{hi:g} s",
                    step=self.name, details={"checks": checks},
                )  # fmt: skip
            await asyncio.to_thread(self._sample_frames, rctx, ctx.settings.render.glyph_sample_s, checks)
            silent = tmpd / "video.en.silent.mp4"
            stats = await asyncio.to_thread(
                render_video, resolved, silent, tmpd / "chunks", fonts_dir=self.fonts_dir,
                settings=values, reading_wps=reading_wps(ctx), limit_frames=self.limit_frames,
            )  # fmt: skip
            expected = min(rctx.timeline.frames, self.limit_frames or rctx.timeline.frames)
            checks["frames"] = {
                "status": "pass" if stats.frames == expected else "fail",
                "value": stats.frames,
                "limit": expected,
            }
            wav = tmpd / "sfx.en.wav"
            try:
                cues = await asyncio.to_thread(render_sound, rctx, wav, AudioSettings.from_settings(values))
            except MediaError as exc:
                checks["cues_match_animations"] = {"status": "fail", "value": str(exc), "limit": "all"}
                raise StepError(
                    "fatal", "check_failed", str(exc), step=self.name, details={"checks": checks}
                ) from exc
            checks["cues_match_animations"] = {"status": "pass", "value": len(cues), "limit": "all"}
            sh = ctx.settings.render.sheet
            times = [
                s + 0.6 * sc.duration
                for s, sc in zip(rctx.timeline.starts, rctx.timeline.scenes, strict=True)
            ]
            sheet = tmpd / "sheet.en.jpg"
            img = await asyncio.to_thread(
                build_sheet, rctx, times, cols=sh.cols, thumb_w=sh.thumb_w, overlay=sh.safe_overlay
            )
            img.convert("RGB").save(sheet, "JPEG", quality=88)
            st = ctx.storage
            out = {
                "video.en.silent.mp4": await st.put_file(
                    ctx.key(self.name, "video.en.silent.mp4"), silent, kind="video"
                ),
                "sfx.en.wav": await st.put_file(ctx.key(self.name, "sfx.en.wav"), wav, kind="audio"),
                "sheet.en.jpg": await st.put_file(ctx.key(self.name, "sheet.en.jpg"), sheet, kind="image"),
            }
            for name, data in (
                ("resolved.en.json", jdump(resolved)),
                ("checks.render.json", jdump(checks)),
                ("timeline.en.json", jdump(rctx.timeline.as_json())),
            ):
                out[name] = await st.put_bytes(ctx.key(self.name, name), data, kind="json")
        return out

    def _sample_frames(self, rctx: Any, step_s: float, checks: dict[str, Any]) -> None:
        """Strict canvas every `glyph_sample_s`: a missing glyph or a safe-zone breach fails the step."""
        t, last = 0.0, rctx.timeline.total_s
        limit = (self.limit_frames or 10**9) / rctx.timeline.fps
        try:
            while t < min(last, limit):
                render_frame(rctx, t, strict=True)
                t += max(step_s, 0.05)
        except GlyphMissing as exc:
            checks["glyphs"] = {"status": "fail", "value": str(exc), "limit": 0}
            raise StepError(
                "fatal", "check_failed", f"glyph check: {exc}", step=self.name, details={"checks": checks}
            ) from exc
        except SafeZoneError as exc:
            checks["safe_zone"] = {"status": "fail", "value": str(exc), "limit": 0}
            raise StepError(
                "fatal", "check_failed", f"safe zone: {exc}", step=self.name, details={"checks": checks}
            ) from exc
        checks["glyphs"] = {"status": "pass", "value": 0, "limit": 0}
        checks["safe_zone"] = {"status": "pass", "value": 0, "limit": 0}


async def json_of(ctx: RunContext, step: str, name: str) -> Any:
    return json.loads(await ctx.storage.get_bytes(ctx.outputs[step][name].ref))


class PackageStep(AgentStep):
    name = "package"
    lo, hi = 90, 100
    produces = ("post.en.json",)
    settings_keys = ("post", "audio", "platform", "prompt_versions")

    def __init__(self, *, fonts_dir: str | None = None) -> None:
        self.fonts_dir = fonts_dir
        self._capture: dict[str, str] = {}
        self._template: str | None = None
        self._tags: list[str] = []
        self._source = ""

    async def inputs(self, ctx: RunContext) -> dict[str, bytes]:
        get = ctx.storage.get_bytes
        return {
            "script.en.json": await get(ctx.outputs["script"]["script.en.json"].ref),
            "research.json": await get(ctx.outputs["research"]["research.json"].ref),
            "channel.json": jdump(channel_json(ctx)),
        }

    async def values(self, ctx: RunContext) -> dict[str, Any]:
        st = ctx.input.channels[0].settings
        tags = list(st.hashtags or []) if st else []
        v = common_values(ctx)
        return {
            "channel_name": v["channel_name"],
            "max_caption_chars": ctx.settings.post.max_caption_chars,
            "max_hashtags": ctx.settings.post.max_hashtags,
            "fixed_hashtags": " ".join(tags) or "none",
        }

    def extra_checks(self, ctx: RunContext, docs: dict[str, Any]) -> list[Issue]:
        post = docs.get("post.en.json")
        if not post or post.get("__unreadable__") or "hook" not in post:
            return []
        _, problems = render_post(
            post,
            self._capture,
            template=self._template,
            channel_hashtags=self._tags,
            source=self._source,
            max_caption_chars=ctx.settings.post.max_caption_chars,
            max_hashtags=ctx.settings.post.max_hashtags,
        )
        return [Issue("post_limits", "/", p, "post.en.json") for p in problems]

    async def run(self, ctx: RunContext) -> dict[str, Artifact]:
        analysis = await json_of(ctx, "analysis", "analysis.json")
        capture = await json_of(ctx, "capture", "capture.json")
        script = await json_of(ctx, "script", "script.en.json")
        st = ctx.input.channels[0].settings
        self._capture = {k: str(v["value"]) for k, v in capture["values"].items()}
        self._template = st.caption_template if st else None
        self._tags = list(st.hashtags or []) if st else []
        self._source = source_label(analysis["system"]["repo"], analysis["system"]["ref"])

        inputs = await self.inputs(ctx)
        req = self.request(ctx, inputs, await self.values(ctx))
        _res, out = await self.agent_loop(ctx, req, inputs)
        post = json.loads(out["post.en.json"])
        rendered, _ = render_post(
            post, self._capture, template=self._template, channel_hashtags=self._tags,
            source=self._source, max_caption_chars=ctx.settings.post.max_caption_chars,
            max_hashtags=ctx.settings.post.max_hashtags,
        )  # fmt: skip
        metadata = build_metadata(script, rendered, post)

        values = ctx.settings.model_dump(mode="json")
        audio = AudioSettings.from_settings(values)
        arts: dict[str, Artifact] = {}
        with tempfile.TemporaryDirectory(prefix="mvideo-package-") as tmp:
            d = Path(tmp)
            for name in ("video.en.silent.mp4", "sfx.en.wav"):
                (d / name).write_bytes(await ctx.storage.get_bytes(ctx.outputs["render"][name].ref))
            resolved = await json_of(ctx, "render", "resolved.en.json")
            timeline = await json_of(ctx, "render", "timeline.en.json")
            rctx = make_context(
                resolved, self.fonts_dir, values, reading_wps=reading_wps(ctx), fps=ctx.settings.video.fps
            )
            final = d / "final.en.mp4"
            try:
                loud = await asyncio.to_thread(
                    mux_final, d / "video.en.silent.mp4", d / "sfx.en.wav", final, audio
                )
            except LoudnessError as exc:
                raise StepError("fatal", "check_failed", str(exc), step=self.name,
                                details=LOUD_FAIL(exc)) from exc  # fmt: skip
            cover = d / "cover.en.jpg"
            await asyncio.to_thread(extract_cover, rctx, _cover_time(script, timeline), cover, 90)
            info = await asyncio.to_thread(probe, final)
            frames = await asyncio.to_thread(count_frames, final)
            size_mb = final.stat().st_size / 1e6
            vs = ctx.settings.video
            checks = {
                "loudness": {
                    "status": "pass",
                    "value": {"lufs": loud.integrated, "true_peak": loud.true_peak},
                    "limit": f"{audio.lufs}±{audio.tolerance_lu} LUFS, <= {audio.true_peak} dBTP",
                },
                "format": {
                    "status": "pass" if (info.width, info.height, info.fps) == (vs.width, vs.height, vs.fps)
                    and info.faststart and info.video_codec == "h264" else "fail",
                    "value": f"{info.video_codec} {info.width}x{info.height}@{info.fps:g}",
                    "limit": f"h264 {vs.width}x{vs.height}@{vs.fps} faststart",
                },
                "bitrate_size": {
                    "status": "pass" if size_mb <= ctx.settings.platform.max_size_mb else "fail",
                    "value": round(size_mb, 1), "limit": ctx.settings.platform.max_size_mb,
                },
                "post_limits": {
                    "status": "pass", "value": len(rendered["caption"]),
                    "limit": ctx.settings.post.max_caption_chars,
                },
            }  # fmt: skip
            failed = {k: v for k, v in checks.items() if v["status"] == "fail"}
            if failed:
                raise StepError("fatal", "check_failed", "package checks failed", step=self.name,
                                details={"checks": failed})  # fmt: skip
            arts["final.en.mp4"] = await ctx.storage.put_file(
                ctx.key(self.name, "final.en.mp4"), final, kind="video"
            )
            arts["cover.en.jpg"] = await ctx.storage.put_file(
                ctx.key(self.name, "cover.en.jpg"), cover, kind="image"
            )
            duration = round(frames / info.fps, 3)
            size, width, height, fps = final.stat().st_size, info.width, info.height, int(info.fps)
        variant = {
            "post": {"caption": rendered["caption"], "hashtags": rendered["hashtags"]},
            "metadata": metadata, "checks": checks,
            "video": {"duration_s": duration, "size": size, "width": width, "height": height, "fps": fps},
        }  # fmt: skip
        arts["post.en.json"] = await ctx.storage.put_bytes(
            ctx.key(self.name, "post.en.json"), jdump(post), kind="json"
        )
        arts["variant.en.json"] = await ctx.storage.put_bytes(
            ctx.key(self.name, "variant.en.json"), jdump(variant), kind="json"
        )
        return arts


def _cover_time(script: dict[str, Any], timeline: dict[str, Any]) -> float:
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


async def finalize_real(ctx: RunContext) -> tuple[dict[str, Any], list[Artifact]]:
    """The result `output` (04 section 2.5) from the artifacts of the steps."""
    pkg, render = ctx.outputs["package"], ctx.outputs["render"]
    extra = await json_of(ctx, "package", "variant.en.json")
    checks = {**await json_of(ctx, "render", "checks.render.json"), **extra["checks"]}
    video = pkg["final.en.mp4"]
    output = {
        "variants": [
            {
                "language": "en",
                "video": {"ref": video.ref, "sha256": video.sha256, **extra["video"]},
                "contact_sheet": render["sheet.en.jpg"].ref,
                "cover": pkg["cover.en.jpg"].ref,
                "post": extra["post"],
                "metadata": extra["metadata"],
                "checks": checks,
            }
        ],
        "provenance": {
            "prompts": {
                s: f"{s}@{ctx.settings.prompt_versions.get(s, '1.0.0')}"
                for s in ("analysis", "research", "script", "capture", "package")
            },
            "skill": f"explainer-video@{ctx.settings.prompt_versions.get('skill', '1.0.0')}",
            "model": ctx.settings.model,
            "auth_mode": ctx.settings.agent.auth.mode,
            "cost_mode": ctx.settings.resolved_cost_mode(),
        },
        "changes": None,
    }
    return output, [a for files in ctx.outputs.values() for a in files.values()]
