from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest
from mvrender import media

from helpers import FakeRunner, ScriptedPlanner, Trees, load
from mvgen.capture import CaptureFailure, CaptureService
from mvgen.service import GenerationService
from mvgen.settings import Limits, design_brief, values_from_idea
from mvgen.store import LocalStore

needs_ffmpeg = pytest.mark.skipif(media.find_ffmpeg() is None, reason="ffmpeg not available")
FONTS = Path(__file__).resolve().parents[3] / "packages" / "mvrender" / "fonts"


def scenario() -> dict:  # type: ignore[type-arg]
    research = {"system": {"repo": "https://github.com/postgres/postgres", "ref": "REL_17_STABLE"}, "commit": "a" * 40}
    return {"script": load("script.en.json"), "post": load("post.en.json"), "research": research}


def idea(**over) -> dict:  # type: ignore[no-untyped-def,type-arg]
    base = {
        "idea_ref": "idea:1:v1", "environment": {"sandbox_image": "postgres17", "version_expect": "17"},
        "constraints": {"duration_s": {"min": 100, "max": 200}}, "palette": {}, "instructions": {},
    }  # fmt: skip
    return {**base, **over}


def make(sm, tmp_path: Path, runner: FakeRunner | None = None, **kw) -> tuple[GenerationService, Trees, FakeRunner]:  # type: ignore[no-untyped-def]
    runner = runner or FakeRunner()
    trees = Trees()
    captures = CaptureService(sm, ScriptedPlanner(load("capture.plan.json")), runner)
    return GenerationService(sm, captures, trees, LocalStore(tmp_path / "store"), fonts_dir=FONTS, **kw), trees, runner


def test_idea_drives_limits_palette_and_brief() -> None:
    i = idea(
        constraints={"duration_s": {"min": 25, "max": 40}, "reading_wps": 3.5, "max_cost_usd": 0.4, "fps": 30},
        palette={"ink": "#112233"}, video_brief="slow and calm", design_notes="cold colours",
        instructions={"video": "no zoom"}, must_show=["oid"],
    )  # fmt: skip
    lim = Limits.from_idea(i)
    assert (lim.duration_min_s, lim.duration_max_s, lim.reading_wps, lim.max_cost_usd) == (25, 40, 3.5, Decimal("0.4"))
    v = values_from_idea(i, {"palette": {"ink": "#000000", "accent": "#ff0000"}, "video": {"crf": 20}})
    assert v["palette"] == {"ink": "#112233", "accent": "#ff0000"} and v["video"] == {"crf": 20, "fps": 30}
    assert design_brief(i) == {
        "video_brief": "slow and calm", "design_notes": "cold colours", "instructions": "no zoom",
        "must_show": ["oid"], "must_avoid": [],
    }  # fmt: skip


def test_defaults_when_the_idea_sets_nothing() -> None:
    lim = Limits.from_idea({})
    assert (lim.duration_min_s, lim.duration_max_s) == (20, 60) and lim.max_hashtags == 8
    assert values_from_idea({}) == {"video": {}}


async def test_duration_outside_the_idea_limits_is_a_stored_failure(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    svc, trees, runner = make(sm, tmp_path)
    out = await svc.run(idea(constraints={"duration_s": {"min": 20, "max": 45}}), scenario(), "run1:video")
    assert out.status == "failed" and out.document["code"] == "duration"
    assert out.document["checks"]["duration"]["limit"] == "20-45"
    assert trees.opened and runner.calls == 1
    again = await svc.run(idea(), scenario(), "run1:video")  # same step_key: stored, nothing runs
    assert again.status == "failed" and runner.calls == 1 and len(trees.opened) == 1


async def test_blocked_capture_is_a_stored_failure(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    runner = FakeRunner(fail=[CaptureFailure("version_mismatch", "got 16")])
    svc, _, _ = make(sm, tmp_path, runner)
    out = await svc.run(idea(), scenario(), "run2:video")
    assert out.status == "failed" and out.document["code"] == "version_mismatch"
    assert out.usage.cost_usd == 0  # the failed attempt cost is part of the stored usage only when produced


async def test_unresolvable_script_is_a_failed_resolve(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sc = scenario()
    sc["script"] = copy.deepcopy(sc["script"])
    sc["script"]["sources"]["utility.c"] = "src/missing.c"
    svc, _, _ = make(sm, tmp_path)
    out = await svc.run(idea(), sc, "run3:video")
    assert out.status == "failed" and out.document["code"] == "resolve"


@needs_ffmpeg
async def test_full_run_on_the_reference(sm, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    svc, _, _ = make(sm, tmp_path, limit_frames=120)
    sc = scenario()
    out = await svc.run(
        idea(constraints={"duration_s": {"min": 100, "max": 200}, "max_hashtags": 10}), sc, "run4:video"
    )
    assert out.status == "done", out.document
    v = out.document["variants"][0]
    assert v["checks"]["loudness"]["status"] == "pass" and v["video"]["ref"].startswith("file://")
