"""Fake steps: sleep and write small files to S3, so the whole flow is testable before the real
steps exist (build prompt B2). Replaced step by step in phases B4 to B8."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from mvideo.pipeline.context import RunContext
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.base import Step
from mvideo.storage import Artifact

PLAN: tuple[tuple[str, int, int, dict[str, str]], ...] = (
    ("analysis", 0, 5, {"analysis.json": "json"}),
    ("research", 5, 20, {"research.json": "json"}),
    ("script", 20, 35, {"script.en.json": "json"}),
    ("capture", 35, 45, {"capture.json": "json"}),
    ("render", 45, 90, {"sheet.en.jpg": "image"}),
    ("package", 90, 100, {"final.en.mp4": "video", "cover.en.jpg": "image", "post.en.json": "json"}),
)


class FakeStep(Step):
    def __init__(
        self,
        name: str,
        lo: int,
        hi: int,
        files: dict[str, str],
        *,
        sleep_s: float = 0.0,
        uses_agent: bool = False,
        fail_with: StepError | None = None,
        on_run: Callable[[RunContext], Awaitable[None]] | None = None,
        settings_keys: tuple[str, ...] = ("video",),
    ) -> None:
        self.name = name
        self.lo = lo
        self.hi = hi
        self.files = files
        self.sleep_s = sleep_s
        self.uses_agent = uses_agent
        self.fail_with = fail_with
        self.on_run = on_run
        self.settings_keys = settings_keys
        self.calls = 0

    async def run(self, ctx: RunContext) -> dict[str, Artifact]:
        self.calls += 1
        if self.on_run is not None:
            await self.on_run(ctx)
        await asyncio.sleep(self.sleep_s)
        if self.fail_with is not None:
            raise self.fail_with
        out: dict[str, Artifact] = {}
        for filename, kind in self.files.items():
            body = (
                json.dumps({"step": self.name, "idea": ctx.idea.get("title")}).encode()
                if kind == "json"
                else f"fake {kind} of {self.name}".encode()
            )
            out[filename] = await ctx.storage.put_bytes(ctx.key(self.name, filename), body, kind=kind)
        return out


def fake_pipeline(**overrides: Any) -> list[FakeStep]:
    """The six stage-1 steps as fakes. `overrides` maps a step name to FakeStep keyword arguments."""
    return [FakeStep(name, lo, hi, files, **overrides.get(name, {})) for name, lo, hi, files in PLAN]


def fake_finalize(ctx: RunContext) -> tuple[dict[str, Any], list[Artifact]]:
    """Build a result `output` that validates against the `video` output schema (04 section 2.5)."""
    pkg = ctx.outputs["package"]
    render = ctx.outputs["render"]
    video = pkg["final.en.mp4"]
    output = {
        "variants": [
            {
                "language": "en",
                "video": {
                    "ref": video.ref,
                    "sha256": video.sha256,
                    "duration_s": 61.0,
                    "size": video.size,
                    "width": 1080,
                    "height": 1920,
                    "fps": 60,
                },
                "contact_sheet": render["sheet.en.jpg"].ref,
                "cover": pkg["cover.en.jpg"].ref,
                "post": {"caption": "Fake caption", "hashtags": ["postgresql"]},
                "metadata": {
                    "title": "Fake title",
                    "description": "Fake description",
                    "topics": ["postgresql"],
                    "platforms": {"instagram": {"caption": "Fake caption", "hashtags": ["#postgresql"]}},
                },
                "checks": {"duration": {"status": "pass", "value": 61.0, "limit": "60-180"}},
            }
        ],
        "provenance": {"fake": True, "renderer_version": "0.2.0"},
        "changes": None,
    }
    artifacts = [a for files in ctx.outputs.values() for a in files.values()]
    return output, artifacts
