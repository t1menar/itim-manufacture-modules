"""B9: revise mode: diff, changes check, reuse decisions, script-revise with the replay agent."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.agents.launcher import ReplayLauncher
from mvideo.config import BootstrapConfig
from mvideo.contract import Previous
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.analysis import ReviseScriptStep
from mvideo.pipeline.steps.media_steps import ReviseCaptureStep, RevisePackageStep, finalize_real
from mvideo.revise import (
    check_changes,
    command_signature,
    hook_inputs,
    render_changes,
    structural_diff,
    values_changed,
)
from mvideo.storage import Storage
from tests import refdata
from tests.harness import build_harness
from tests.helpers import job_request
from tests.test_steps import make_ctx, replay

REASON = "Step 9 is too fast, I could not read the notes"


def reference() -> dict[str, Any]:
    return copy.deepcopy(refdata.load("script.en.json"))


def slower(script: dict[str, Any]) -> dict[str, Any]:
    new = copy.deepcopy(script)
    new["scenes"][-1]["tail_s"] = 3.0  # an optional number that does not touch commands or the hook
    return new


def changes_for(old: dict[str, Any], new: dict[str, Any], **extra: Any) -> dict[str, Any]:
    items = [
        {"path": p, "before": a, "after": b, "why": "slower"}
        for p, (a, b) in structural_diff(old, new).items()
    ]
    return {
        "format": "manufacture.changes/1",
        "reason_quote": REASON,
        "summary": "Slowed down",
        "items": items,
        **extra,
    }


# ---- diff, check, rendering --------------------------------------------------------------------


def test_structural_diff_lists_leaves_adds_removes_and_length_changes() -> None:
    old = {"a": {"b": 1, "c": [1, 2]}, "d": [1, 2], "e": "x"}
    new = {"a": {"b": 2, "c": [1, 3]}, "d": [1, 2, 3], "f": True}
    assert structural_diff(old, new) == {
        "/a/b": (1, 2), "/a/c/1": (2, 3), "/d": ([1, 2], [1, 2, 3]), "/e": ("x", None), "/f": (None, True),
    }  # fmt: skip
    assert structural_diff(old, old) == {}


def test_changes_must_equal_the_diff_exactly() -> None:
    old = reference()
    new = slower(old)
    good = changes_for(old, new)
    assert check_changes(good, old, new) == []
    missing = {**good, "items": []}
    extra = {
        **good,
        "items": [*good["items"], {"path": "/meta/title", "before": "a", "after": "b", "why": "x"}],
    }
    wrong = {**good, "items": [{**good["items"][0], "after": 99}]}
    assert "not listed" in check_changes(missing, old, new)[0].message
    assert "did not change" in check_changes(extra, old, new)[0].message
    assert "differ" in check_changes(wrong, old, new)[0].message


def test_changes_text_summary_items_and_values_changed() -> None:
    old = reference()
    new = slower(old)
    text = render_changes(changes_for(old, new), ["n_pages: 298 → 301"], 1500)
    lines = text.splitlines()
    assert lines[0] == "Slowed down" and "→" in lines[1] and "(slower)" in lines[1]
    assert lines[-1] == "values changed: n_pages: 298 → 301"
    assert len(render_changes(changes_for(old, new), [], 40)) == 40


def test_reuse_signals() -> None:
    old = reference()
    assert command_signature(old) == command_signature(slower(old))
    other = reference()
    ev = next(e for sc in other["scenes"] for e in (sc.get("terminal") or {}).get("events", []) if "cmd" in e)
    ev["text"] += " "
    assert command_signature(old) != command_signature(other)
    hooked = reference()
    hooked["meta"]["hook"] = "Another hook."
    assert hook_inputs(old) == hook_inputs(slower(old)) and hook_inputs(old) != hook_inputs(hooked)


def test_values_changed_lists_only_used_captures() -> None:
    old = {"values": {"n_pages": {"value": "298"}, "unused": {"value": "1"}}}
    new = {"values": {"n_pages": {"value": "301"}, "unused": {"value": "2"}}}
    assert values_changed(old, new, {"captures": {"n_pages": {}}}) == ["n_pages: 298 → 301"]


# ---- script-revise with the replay agent ------------------------------------------------------


async def revise_ctx(tmp_path: Path, **kw: Any) -> Any:
    ctx = make_ctx(ReplayLauncher(tmp_path), **kw)
    ctx.input.previous = Previous(script_ref="s3://t/prev/script.en.json", review_reason=REASON, round=1)
    st = ctx.storage
    put = lambda k, d: st.put_bytes(k, json.dumps(d).encode(), kind="json")  # noqa: E731
    ctx.previous = {
        "script": {"script.en.json": await put("prev/script.en.json", refdata.load("script.en.json"))},
        "capture": {"capture.json": await put("prev/capture.json", refdata.load("capture.json"))},
        "package": {"post.en.json": await put("prev/post.en.json", refdata.load("post.en.json"))},
    }
    ctx.outputs["analysis"] = {"analysis.json": await put("a", refdata.load("analysis.json"))}
    ctx.outputs["research"] = {"research.json": await put("r", refdata.load("research.json"))}
    return ctx


def replay_revision(tmp_path: Path, new: dict[str, Any], changes: dict[str, Any], call: int = 1) -> None:
    replay(tmp_path, "script-revise", call=call, content={
        "script.en.json": json.dumps(new).encode(), "changes.en.json": json.dumps(changes).encode(),
    })  # fmt: skip


async def test_revise_accepts_a_minimal_edit_with_a_matching_changes_list(tmp_path: Path) -> None:
    old = reference()
    new = slower(old)
    replay_revision(tmp_path, new, changes_for(old, new))
    ctx = await revise_ctx(tmp_path)
    ctx.source = refdata.synthetic_source(old, refdata.load("research.json"))
    out = await ReviseScriptStep().run(ctx)
    assert {"script.en.json", "changes.en.json"} <= set(out)
    ctx.outputs["script-revise"] = out
    assert json.loads(await ctx.storage.get_bytes(ctx.files("script")["script.en.json"].ref)) == new


async def test_revise_resumes_when_changes_do_not_match_the_diff(tmp_path: Path) -> None:
    old = reference()
    new = slower(old)
    replay_revision(tmp_path, new, {**changes_for(old, new), "items": changes_for(old, new)["items"][:0] or [
        {"path": "/meta/title", "before": "a", "after": "b", "why": "x"}]})  # fmt: skip
    replay_revision(tmp_path, new, changes_for(old, new), call=2)
    ctx = await revise_ctx(tmp_path)
    ctx.source = refdata.synthetic_source(old, refdata.load("research.json"))
    launcher = ctx.launcher
    await ReviseScriptStep().run(ctx)
    assert [c.step for c in launcher.calls] == [
        "script-revise"
    ] * 2  # the first answer failed revise_diff, the resume fixed it


async def test_revise_that_cannot_be_applied_is_blocked(tmp_path: Path) -> None:
    blocked = {"format": "manufacture.blocked/1", "step": "script-revise", "code": "facts_missing",
               "reason": "The channel rules forbid showing the commit hash in a video, so I skipped it.",
               "missing": [], "suggestion": "Ask the owner to change the channel rule first."}  # fmt: skip
    replay(tmp_path, "script-revise", content={"blocked.json": json.dumps(blocked).encode()})
    ctx = await revise_ctx(tmp_path)
    with pytest.raises(StepError) as exc:
        await ReviseScriptStep().run(ctx)
    assert exc.value.error_class == "blocked"


# ---- reuse decisions ----------------------------------------------------------------------------


async def test_caption_only_revise_starts_no_sandbox_and_no_agent(tmp_path: Path) -> None:
    old = reference()
    ctx = await revise_ctx(tmp_path)
    ctx.launcher = None  # any agent call would fail
    ctx.docker = None  # any sandbox use would fail
    ctx.outputs["script-revise"] = {
        "script.en.json": await ctx.storage.put_bytes("n/s", json.dumps(slower(old)).encode(), kind="json")
    }
    capture = await ReviseCaptureStep().run(ctx)
    assert capture == ctx.previous["capture"] and ctx.sandbox_used is False
    post = await RevisePackageStep().get_post(ctx)
    assert post == refdata.load("post.en.json")


async def test_changed_hook_reruns_the_package_agent(tmp_path: Path) -> None:
    old = reference()
    new = reference()
    new["meta"]["hook"] = "Another hook."
    ctx = await revise_ctx(tmp_path)
    ctx.launcher = None
    ctx.outputs["script-revise"] = {
        "script.en.json": await ctx.storage.put_bytes("n/s", json.dumps(new).encode(), kind="json")
    }
    del old
    with pytest.raises(AttributeError):  # reached the launcher: the agent would have run
        await RevisePackageStep().get_post(ctx)


async def test_result_carries_the_rendered_changes_text(tmp_path: Path) -> None:
    old = reference()
    new = slower(old)
    ctx = await revise_ctx(tmp_path)
    ctx.mode = "revise"
    ctx.values_changed = ["n_pages: 298 → 301"]
    put = ctx.storage.put_bytes
    ctx.outputs["script-revise"] = {
        "script.en.json": await put("n/s", json.dumps(new).encode(), kind="json"),
        "changes.en.json": await put("n/c", json.dumps(changes_for(old, new)).encode(), kind="json"),
    }
    from mvideo.pipeline.steps.media_steps import _changes_text

    text = await _changes_text(ctx)
    assert text is not None and text.startswith("Slowed down") and text.endswith("n_pages: 298 → 301")
    assert finalize_real is not None


# ---- the previous run ---------------------------------------------------------------------------


async def test_revise_job_loads_the_previous_run_and_fails_without_one(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    h = build_harness(engine, storage, config)
    production = uuid.uuid4()
    lonely = await h.submit(production_id=uuid.uuid4(), mode="revise", **_revise_input())
    first = await h.submit(production_id=production)
    await h.run_all()
    assert (await h.run_row(first)).status == "succeeded"
    revise = await h.submit(production_id=production, attempt=2, mode="revise", **_revise_input())
    await h.run_all()
    assert (await h.run_row(revise)).status == "succeeded"
    assert (await h.run_row(lonely)).status == "failed"
    assert h.core.fails[0][1]["details"]["code"] == "input_invalid"


def _revise_input() -> dict[str, Any]:
    body = job_request()
    body["input"]["previous"] = {"script_ref": "s3://t/p/script.en.json", "review_reason": REASON, "round": 1}
    return {"input": body["input"], "variant": {"id": str(uuid.uuid4()), "language": "en"}}
