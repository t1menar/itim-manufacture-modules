"""B8: Claude steps with the replay agent: placeholders, blocked, schema retries, resume."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest

from mvideo.agents.launcher import ReplayLauncher
from mvideo.contract import Channel, ChannelSettings, Idea, JobInput
from mvideo.core_client import Credential
from mvideo.pipeline.context import RunContext
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.analysis import AnalysisStep, ResearchStep, ScriptStep
from mvideo.settings_model import VideoSettings
from mvideo.storage import Artifact
from tests import refdata
from tests.helpers import settings_values


class MemStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_bytes(self, key: str, data: bytes, *, kind: str, content_type: str = "") -> Artifact:
        self.objects[f"s3://t/{key}"] = data
        return Artifact(f"s3://t/{key}", hashlib.sha256(data).hexdigest(), len(data), kind)

    async def put_file(self, key: str, path: Path, *, kind: str, content_type: str = "") -> Artifact:
        return await self.put_bytes(key, await asyncio.to_thread(path.read_bytes), kind=kind)

    async def get_bytes(self, ref: str) -> bytes:
        return self.objects[ref]


class FakeGit:
    commit = "e6b2f7c2b41d6261dac15825dede55e94ca35614"

    async def resolve_commit(self, settings: Any, url: str, ref: str) -> str:
        return self.commit

    async def ensure(self, settings: Any, url: str, commit: str) -> str:
        return f"video-src-fake-{commit[:12]}"


def make_ctx(launcher: ReplayLauncher, storage: MemStorage | None = None, **settings: Any) -> RunContext:
    return RunContext(
        run_id=uuid.uuid4(), job_id=uuid.uuid4(), attempt=1, production_id=uuid.uuid4(), mode="create",
        input=JobInput(
            idea=Idea(id=42, text="Detailed implementation of CREATE DATABASE in PostgreSQL", language="en"),
            channels=[
                Channel(id="itim", language="en", name="iTim", settings=ChannelSettings(reading_wps=2.6))
            ],
        ),
        settings=VideoSettings.model_validate(settings_values(**settings)),
        storage=storage or MemStorage(),  # type: ignore[arg-type]
        credential=Credential("cred:x", "claude_oauth_token", "sk-secret"),
        launcher=launcher, git_cache=FakeGit(),
    )  # fmt: skip


def replay(
    tmp_path: Path, step: str, *files: str, call: int = 1, content: dict[str, bytes] | None = None
) -> None:
    d = tmp_path / step / ("files" if call == 1 else f"files.{call}")
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy(refdata.REFERENCE / f, d / f)
    for name, data in (content or {}).items():
        (d / name).write_bytes(data)


async def run_analysis(tmp_path: Path, **kw: Any) -> tuple[dict[str, Artifact], RunContext, ReplayLauncher]:
    launcher = ReplayLauncher(tmp_path)
    ctx = make_ctx(launcher, **kw)
    return await AnalysisStep().run(ctx), ctx, launcher


async def test_analysis_runs_validates_and_uploads(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", "analysis.json")
    arts, ctx, launcher = await run_analysis(tmp_path)
    assert set(arts) == {"analysis.json", "_transcript.jsonl"}
    assert json.loads(ctx.storage.objects[arts["analysis.json"].ref])["system"]["name"]  # type: ignore[attr-defined]
    req = launcher.calls[0]
    assert "idea 42" in req.prompt and "iTim" in req.prompt and "postgres17" in req.prompt
    assert "CLAUDE.md" in req.workspace.work and "schemas/analysis.schema.json" in req.workspace.work
    assert ".claude/skills/explainer-video/SKILL.md" in req.workspace.work
    assert {"idea.json", "environment.json", "channel.json"} <= set(req.workspace.inputs)
    assert "create_database/analysis.json" in req.workspace.ref
    assert len(ctx.usage) == 1


async def test_blocked_json_becomes_blocked_idea_not_showable(tmp_path: Path) -> None:
    blocked = {
        "format": "manufacture.blocked/1", "step": "analysis", "missing": ["an Oracle sandbox image"],
        "reason": "Oracle RAC cannot be run in any sandbox image we have, so nothing is shown honestly.",
    }  # fmt: skip
    replay(tmp_path, "analysis", content={"blocked.json": json.dumps(blocked).encode()})
    with pytest.raises(StepError) as e:
        await run_analysis(tmp_path)
    assert (e.value.error_class, e.value.code) == ("blocked", "idea_not_showable")
    assert e.value.details["missing"] == ["an Oracle sandbox image"]


async def test_invalid_output_is_resumed_with_the_validator_report(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", content={"analysis.json": b'{"format": "wrong"}'})
    replay(tmp_path, "analysis", "analysis.json", call=2)
    arts, _, launcher = await run_analysis(tmp_path)
    assert "analysis.json" in arts and len(launcher.calls) == 2
    second = launcher.calls[1]
    assert second.resume == "replay-analysis"
    assert "validation_errors.json" in second.workspace.inputs
    assert "Fix exactly these" in second.prompt


async def test_output_still_invalid_after_retries_is_schema_invalid(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", content={"analysis.json": b'{"format": "wrong"}'})
    with pytest.raises(StepError) as e:
        await run_analysis(tmp_path)
    assert (e.value.error_class, e.value.code) == ("fatal", "schema_invalid")
    assert e.value.details["issues"]


async def test_analysis_outside_the_environment_is_rejected(tmp_path: Path) -> None:
    doc = refdata.load("analysis.json")
    doc["sandbox_image"] = "oracle19"
    replay(tmp_path, "analysis", content={"analysis.json": json.dumps(doc).encode()})
    with pytest.raises(StepError) as e:
        await run_analysis(tmp_path)
    assert e.value.code == "schema_invalid"
    assert any("sandbox_image" in str(i) for i in e.value.details["issues"])


async def test_research_and_script_read_upstream_files(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", "analysis.json")
    replay(tmp_path, "research", "research.json")
    replay(tmp_path, "script", "script.en.json")
    launcher = ReplayLauncher(tmp_path)
    ctx = make_ctx(launcher)
    ctx.outputs["analysis"] = await AnalysisStep().run(ctx)
    ctx.outputs["research"] = await ResearchStep().run(ctx)
    ctx.fix_reports["script"] = "caption_fit: scene s3 is too wide"
    ctx.outputs["script"] = await ScriptStep().run(ctx)
    research_req = launcher.calls[1]
    assert "e6b2f7c2b41d6261dac15825dede55e94ca35614" in research_req.prompt
    script_req = launcher.calls[2]
    assert "caption_fit: scene s3 is too wide" in script_req.prompt
    assert {"research.json", "analysis.json", "limits.json"} <= set(script_req.workspace.inputs)
    assert "script.en.json" in ctx.outputs["script"]
