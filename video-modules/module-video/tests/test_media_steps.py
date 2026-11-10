"""B8: post rendering, the result builder, and the capture/render steps with the replay agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mvideo.agents.launcher import ReplayLauncher
from mvideo.contract import StageOutput
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.media_steps import CaptureStep, RenderStep, finalize_real
from mvideo.post import build_metadata, render_post, source_label
from tests import refdata
from tests.test_render import SOURCES, Tree
from tests.test_sandbox import docker_client, pg_ref, pg_settings  # noqa: F401
from tests.test_steps import MemStorage, make_ctx, replay

FONTS = str(Path(__file__).resolve().parents[1] / "fonts")
POST = {"hook": "H {n}", "summary": "S", "topic_hashtags": ["postgresql", "#sql"]}


def rp(**kw: Any) -> tuple[dict[str, Any], list[str]]:
    args: dict[str, Any] = {
        "template": None, "channel_hashtags": ["#itim"], "source": "github.com/x/y · REL_17_STABLE",
        "max_caption_chars": 2200, "max_hashtags": 30,
    }  # fmt: skip
    return render_post(kw.pop("post", POST), {"n": "7"}, **{**args, **kw})


def test_caption_fills_capture_placeholders_and_source() -> None:
    out, problems = rp()
    assert not problems
    assert out["hook"] == "H 7"
    assert out["caption"] == "H 7\n\nS\n\nSource: github.com/x/y · REL_17_STABLE"
    assert out["hashtags"] == ["#itim", "#postgresql", "#sql"]


def test_channel_template_and_dedup() -> None:
    out, _ = rp(template="{hook} | {source}", channel_hashtags=["#SQL", "#x"])
    assert out["caption"].startswith("H 7 | github.com/x/y")
    assert out["hashtags"] == ["#SQL", "#x", "#postgresql"]


def test_limits_unknown_placeholder_and_commit_hash() -> None:
    _, p1 = rp(max_caption_chars=10)
    _, p2 = rp(max_hashtags=1)
    _, p3 = rp(post={**POST, "summary": "{nope}"})
    _, p4 = rp(post={**POST, "summary": "e6b2f7c2b41d6261dac15825dede55e94ca35614"})
    assert "limit 10" in p1[0] and "limit 1" in p2[0]
    assert "nope" in p3[0] and "commit" in p4[0]


def test_source_label_has_no_commit() -> None:
    assert source_label("https://github.com/postgres/postgres/", "REL_17_STABLE") == (
        "github.com/postgres/postgres · REL_17_STABLE"
    )


def test_metadata_is_built_from_script_and_post() -> None:
    script = refdata.load("script.en.json")
    rendered, _ = rp()
    md = build_metadata(script, rendered, POST)
    assert md["title"] == "How CREATE DATABASE works"
    assert md["topics"] == ["postgresql", "sql"]
    assert md["platforms"]["instagram"]["hashtags"][0] == "#itim"


async def test_finalize_real_validates_against_the_output_schema(tmp_path: Path) -> None:
    ctx = make_ctx(None)  # type: ignore[arg-type]
    st: MemStorage = ctx.storage  # type: ignore[assignment]
    put = st.put_bytes
    script = refdata.load("script.en.json")
    rendered, _ = rp()
    ctx.outputs = {
        "render": {
            "sheet.en.jpg": await put("k/sheet", b"j", kind="image"),
            "checks.render.json": await put("k/c", b'{"duration": {"status": "pass"}}', kind="json"),
        },
        "package": {
            "final.en.mp4": await put("k/final", b"v", kind="video"),
            "cover.en.jpg": await put("k/cover", b"c", kind="image"),
            "variant.en.json": await put(
                "k/v",
                json.dumps({
                    "post": {"caption": rendered["caption"], "hashtags": rendered["hashtags"]},
                    "metadata": build_metadata(script, rendered, POST),
                    "checks": {"loudness": {"status": "pass"}},
                    "video": {"duration_s": 61.0, "size": 1, "width": 1080, "height": 1920, "fps": 60},
                }).encode(),
                kind="json",
            ),
        },
    }  # fmt: skip
    output, arts = await finalize_real(ctx)
    parsed = StageOutput.model_validate(output)
    assert parsed.variants[0].metadata.platforms["instagram"].hashtags[0] == "#itim"
    assert set(parsed.variants[0].checks) == {"duration", "loudness"}
    assert len(arts) == 5


@pytest.mark.docker
async def test_capture_step_runs_the_reference_plan_in_the_sandbox(
    tmp_path: Path,
    docker_client: Any,  # noqa: F811
    pg_ref: str,  # noqa: F811
) -> None:
    replay(tmp_path, "capture", "capture.plan.json")
    ctx = make_ctx(ReplayLauncher(tmp_path))
    ctx.settings = pg_settings(pg_ref)
    ctx.docker = docker_client
    st = ctx.storage
    for step, name in (
        ("analysis", "analysis.json"),
        ("research", "research.json"),
        ("script", "script.en.json"),
    ):
        ctx.outputs.setdefault(step, {})[name] = await st.put_bytes(
            f"k/{name}", json.dumps(refdata.load(name)).encode(), kind="json"
        )
    out = await CaptureStep().run(ctx)
    cap = json.loads(await st.get_bytes(out["capture.json"].ref))
    ref = refdata.load("capture.json")
    assert {k: v["value"] for k, v in cap["values"].items()} == {
        k: v["value"] for k, v in ref["values"].items()
    }


async def test_render_step_with_limited_frames(tmp_path: Path) -> None:
    ctx = make_ctx(ReplayLauncher(tmp_path))
    st = ctx.storage
    for step, name in (
        ("analysis", "analysis.json"),
        ("script", "script.en.json"),
        ("capture", "capture.json"),
    ):
        ctx.outputs.setdefault(step, {})[name] = await st.put_bytes(
            f"k/{name}", json.dumps(refdata.load(name)).encode(), kind="json"
        )
    ctx.source = Tree(SOURCES)
    ctx.input.channels[0].settings.reading_wps = 4.5  # the pace the reference durations were made with
    out = await RenderStep(limit_frames=30, fonts_dir=FONTS).run(ctx)
    assert {"video.en.silent.mp4", "sfx.en.wav", "sheet.en.jpg", "checks.render.json"} <= set(out)
    checks = json.loads(await st.get_bytes(out["checks.render.json"].ref))
    assert checks["frames"]["status"] == "pass" and checks["glyphs"]["status"] == "pass"


async def test_capture_blocks_with_version_mismatch_code() -> None:
    assert StepError("blocked", "version_mismatch", "x").code == "version_mismatch"
