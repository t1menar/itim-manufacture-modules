"""GenerationService: capture -> render -> package for one approved scenario, stored per `step_key`.

Cost and quality policy, in code:
- the planner agent is the only paid part and is bounded by `constraints.max_cost_usd` of the idea;
- numbers on screen come from the recorded capture; render and packaging are deterministic and free;
- every check is final: a failed check stores a `failed` result and is not retried;
- a retried platform step returns the stored result; a revision reuses the capture when commands are unchanged.
No database transaction is held while the sandbox, the planner or ffmpeg run.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from mvrender.resolve import SourceTree
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvgen.agent import BudgetExceeded, Usage
from mvgen.capture import CaptureBlocked, CaptureService
from mvgen.db import transaction
from mvgen.errors import CheckFailed
from mvgen.models import GenerationResult
from mvgen.package import package
from mvgen.render import render
from mvgen.settings import Limits, design_brief, values_from_idea
from mvgen.store import ArtifactStore


class TreeProvider(Protocol):
    async def open(self, repo: str, commit: str) -> SourceTree: ...


class NoSource:
    """For scripts that cite no source files."""

    def exists(self, path: str) -> bool:
        return False

    def line(self, path: str, n: int) -> str | None:
        return None


@dataclass(slots=True)
class Outcome:
    status: str  # done | failed
    document: dict[str, Any]
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True, slots=True)
class Previous:
    """Artifacts of an earlier visit (a revision): the capture is reused when commands did not change."""

    plan: dict[str, Any]
    capture: dict[str, Any]


class GenerationService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        captures: CaptureService,
        trees: TreeProvider,
        store: ArtifactStore,
        *,
        base_values: Mapping[str, Any] | None = None,
        fonts_dir: str | Path | None = None,
        limit_frames: int | None = None,
    ) -> None:
        self.sm, self.captures, self.trees, self.store = sm, captures, trees, store
        self.base_values, self.fonts_dir, self.limit_frames = base_values, fonts_dir, limit_frames

    async def run(
        self,
        idea: dict[str, Any],
        scenario: dict[str, Any],
        step_key: str,
        *,
        channel: dict[str, Any] | None = None,
        previous: Previous | None = None,
    ) -> Outcome:
        async with transaction(self.sm) as s:
            stored = await s.get(GenerationResult, step_key)
            if stored is not None:
                return Outcome(stored.status, stored.document, Usage(Decimal(stored.cost_usd)))
        usage = Usage()
        try:
            doc, usage = await self._produce(idea, scenario, step_key, channel or {}, previous)
            status = "done"
        except CheckFailed as exc:
            status, doc = "failed", _failed(idea, exc.code, str(exc), exc.checks)
        except CaptureBlocked as exc:
            status, doc = "failed", _failed(idea, exc.code, str(exc), {}, exc.problems)
        except BudgetExceeded as exc:
            status, doc = "failed", _failed(idea, "budget_exceeded", str(exc), {})
        async with transaction(self.sm) as s:
            s.add(
                GenerationResult(
                    step_key=step_key,
                    idea_ref=str(idea["idea_ref"]),
                    status=status,
                    document=doc,
                    cost_usd=usage.cost_usd,
                    usage=usage.as_dict(),
                )  # fmt: skip
            )
        return Outcome(status, doc, usage)

    async def _produce(
        self, idea: dict[str, Any], scenario: dict[str, Any], step_key: str, channel: dict[str, Any],
        previous: Previous | None,
    ) -> tuple[dict[str, Any], Usage]:  # fmt: skip
        script, post, research = scenario["script"], scenario["post"], scenario["research"]
        limits = Limits.from_idea(idea)
        values = values_from_idea(idea, self.base_values)
        env = idea.get("environment") or {}
        image = {
            "key": env.get("sandbox_image") or script["meta"].get("sandbox_image"),
            "version_expect": env.get("version_expect"),
        }
        cap = await self.captures.run(
            script, research, design_brief(idea), image, step_key, limits.max_cost_usd,
            (previous.plan, previous.capture) if previous else None,
        )  # fmt: skip
        system, commit = research.get("system"), research.get("commit")
        source: SourceTree = await self.trees.open(system["repo"], commit) if system and commit else NoSource()
        with tempfile.TemporaryDirectory(prefix="mvgen-") as tmp:
            work = Path(tmp)
            out = await asyncio.to_thread(
                render, script, cap.capture, source, work / "render", values, limits,
                fonts_dir=self.fonts_dir, limit_frames=self.limit_frames,
            )  # fmt: skip
            pk = await asyncio.to_thread(
                package, script, post, cap.capture, system, channel, out.silent, out.sound, out.ctx,
                out.timeline, work, values, limits,
            )  # fmt: skip
            prefix = f"{idea['idea_ref']}/{step_key.replace(':', '_')}"
            video = self.store.put_file(f"{prefix}/final.mp4", pk.final, "video/mp4")
            cover = self.store.put_file(f"{prefix}/cover.jpg", pk.cover, "image/jpeg")
            sheet = self.store.put_file(f"{prefix}/sheet.jpg", out.sheet, "image/jpeg")
        capture_ref = self.store.put_bytes(
            f"{prefix}/capture.json",
            json.dumps({"plan": cap.plan, "capture": cap.capture}).encode(),
            "application/json",
        )
        doc = {
            "format": "manufacture.video/1",
            "idea_ref": idea["idea_ref"],
            "variants": [
                {
                    "language": script["meta"].get("language", "en"),
                    "video": {**video.as_dict(), **pk.video},
                    "cover": cover.as_dict(),
                    "contact_sheet": sheet.as_dict(),
                    "post": pk.post,
                    "metadata": pk.metadata,
                    "checks": {**out.checks, **pk.checks},
                }
            ],
            "capture": {**capture_ref.as_dict(), "reused": cap.cached, "rounds": cap.rounds},
        }
        return doc, cap.usage


def _failed(
    idea: Mapping[str, Any], code: str, message: str, checks: dict[str, Any], problems: list[str] | None = None
) -> dict[str, Any]:
    return {
        "format": "manufacture.video.failed/1", "idea_ref": idea["idea_ref"],
        "code": code, "message": message, "checks": checks, "problems": problems or [],
    }  # fmt: skip


__all__ = ["GenerationService", "NoSource", "Outcome", "Previous", "TreeProvider"]
