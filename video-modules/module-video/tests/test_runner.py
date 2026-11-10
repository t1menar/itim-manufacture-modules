from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.config import BootstrapConfig
from mvideo.contract import StageOutput
from mvideo.core_client import CoreRejected, CoreUnavailable
from mvideo.db import repo
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.fake import fake_pipeline
from mvideo.storage import Storage
from tests.harness import Blocker, Harness, build_harness
from tests.helpers import FakeCore, settings_values

PLAN_NAMES = ["analysis", "research", "script", "capture", "render", "package"]


@pytest.fixture
def harness(engine: AsyncEngine, storage: Storage, config: BootstrapConfig) -> Harness:
    return build_harness(engine, storage, config)


# ---- happy path -------------------------------------------------------------------------------


async def test_run_succeeds_and_sends_one_valid_result(harness: Harness) -> None:
    body = await harness.submit()
    await harness.run_all()

    run = await harness.run_row(body)
    assert run.status == "succeeded"
    assert run.finished_at is not None and run.lease_owner is None

    assert len(harness.core.results) == 1 and harness.core.fails == []
    job_id, payload = harness.core.results[0]
    assert job_id == body["job_id"]
    StageOutput.model_validate(payload["output"])  # what the core will validate
    assert payload["metrics"]["cost_estimated"] is True  # subscription mode: nothing is billed
    assert {a["kind"] for a in payload["artifacts"]} == {"json", "image", "video"}
    assert await harness.storage.verify([_artifact(a) for a in payload["artifacts"]]) == []

    steps = await harness.step_rows(body)
    assert list(steps) == PLAN_NAMES or set(steps) == set(PLAN_NAMES)
    assert all(st.status == "succeeded" and st.input_hash for st in steps.values())


def _artifact(meta: dict[str, object]):  # type: ignore[no-untyped-def]
    from mvideo.storage import Artifact

    return Artifact(**meta)  # type: ignore[arg-type]


async def test_progress_follows_the_step_ranges(harness: Harness) -> None:
    await harness.submit()
    await harness.run_all()
    percents = [p for _, p, _ in harness.core.progress_calls]
    assert percents == [0, 5, 5, 20, 20, 35, 35, 45, 45, 90, 90, 100]
    assert percents == sorted(percents)


async def test_credential_is_fetched_once_per_job(harness: Harness) -> None:
    await harness.submit()
    await harness.run_all()
    assert harness.core.credential_reads == ["CLAUDE_OAUTH_TOKEN"]


async def test_api_status_document_after_success(harness: Harness) -> None:
    body = await harness.submit()
    await harness.run_all()
    async with harness.client() as c:
        doc = (await c.get(f"/v1/jobs/{body['job_id']}")).json()
    assert doc["status"] == "succeeded" and doc["percent"] == 100 and doc["error"] is None
    assert [s["name"] for s in doc["steps"]] and all(s["reused"] is False for s in doc["steps"])


# ---- failures ----------------------------------------------------------------------------------


async def test_step_failure_sends_fail_with_class_code_and_step(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    steps = fake_pipeline(
        capture={
            "fail_with": StepError("fatal", "check_failed", "glyph missing", details={"checks": ["glyphs"]})
        }
    )
    h = build_harness(engine, storage, config, steps=steps)
    body = await h.submit()
    await h.run_all()

    assert h.core.results == []
    ((job_id, fail),) = h.core.fails
    assert job_id == body["job_id"]
    assert fail["class"] == "fatal"
    assert fail["details"] == {"code": "check_failed", "step": "capture", "checks": ["glyphs"]}
    run = await h.run_row(body)
    assert run.status == "failed" and run.error == fail
    rows = await h.step_rows(body)
    assert rows["capture"].status == "failed" and "render" not in rows
    doc = await h.service.status_document(run.job_id)
    assert doc is not None and doc["error"] == {
        "class": "fatal",
        "code": "check_failed",
        "message": "glyph missing",
    }


async def test_blocked_step_is_recorded_as_blocked(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    steps = fake_pipeline(
        analysis={"fail_with": StepError("blocked", "idea_not_showable", "nothing to show")}
    )
    h = build_harness(engine, storage, config, steps=steps)
    body = await h.submit()
    await h.run_all()
    assert h.core.fails[0][1]["class"] == "blocked"
    assert (await h.step_rows(body))["analysis"].status == "blocked"


async def test_unexpected_exception_is_fatal_internal_with_error_id(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    async def boom(_ctx: object) -> None:
        raise ZeroDivisionError("secret detail")

    h = build_harness(engine, storage, config, steps=fake_pipeline(script={"on_run": boom}))
    await h.submit()
    await h.run_all()
    fail = h.core.fails[0][1]
    assert fail["class"] == "fatal" and fail["details"]["code"] == "internal"
    assert fail["details"]["error_id"]
    assert "secret detail" not in fail["message"]  # internals do not leak into callbacks


@pytest.mark.parametrize("failure", ["not_found", "forbidden"])
async def test_missing_credential_blocks_with_agent_auth_failed(harness: Harness, failure: str) -> None:
    harness.core.credential_error = failure
    body = await harness.submit()
    await harness.run_all()
    fail = harness.core.fails[0][1]
    assert fail["class"] == "blocked" and fail["details"]["code"] == "agent_auth_failed"
    assert "claude setup-token" in fail["message"]
    assert await harness.step_rows(body) == {}  # no step ran
    assert await harness.app.state.auth_status() == "missing"


async def test_credential_kind_must_match_the_auth_mode(harness: Harness) -> None:
    harness.core.credential_kind = "anthropic_api_key"  # job is in subscription mode
    await harness.submit()
    await harness.run_all()
    fail = harness.core.fails[0][1]
    assert fail["details"]["code"] == "agent_auth_failed"
    assert "does not match" in fail["message"]


async def test_api_key_mode_accepts_an_api_key_credential_and_is_billed_in_usd(harness: Harness) -> None:
    harness.core.credential_kind = "anthropic_api_key"
    values = settings_values(
        agent={
            "image": settings_values()["agent"]["image"],
            "auth": {"mode": "api_key", "credential_ref": "cred:anthropic-main"},
        }
    )
    await harness.submit(settings=values, credentials=["cred:anthropic-main"])
    await harness.run_all()
    assert len(harness.core.results) == 1
    assert "cost_estimated" not in harness.core.results[0][1]["metrics"]  # usd mode: real cost


async def test_ready_reports_auth_configured_after_a_good_job(harness: Harness) -> None:
    assert await harness.app.state.auth_status() == "missing"
    await harness.submit()
    await harness.run_all()
    assert await harness.app.state.auth_status() == "configured"


async def test_deadline_too_close_fails_transient(harness: Harness) -> None:
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)  # inside the 60 s safety margin
    await harness.submit(deadline=soon)
    await harness.run_all()
    fail = harness.core.fails[0][1]
    assert (fail["class"], fail["details"]["code"]) == ("transient", "deadline")


# ---- usage gates -------------------------------------------------------------------------------


async def test_daily_job_limit_accepts_then_fails_transient_with_retry_after(harness: Harness) -> None:
    limits = settings_values(limits={"max_jobs_per_day": 1})
    first = await harness.submit(settings=limits)
    second = await harness.submit(settings=limits)  # still answered 202
    await harness.run_all()

    assert [j for j, _ in harness.core.results] == [first["job_id"]]
    ((failed_id, fail),) = harness.core.fails
    assert failed_id == second["job_id"]
    assert (fail["class"], fail["details"]["code"]) == ("transient", "daily_job_limit")
    assert 0 < fail["details"]["retry_after"] <= 86400
    async with harness.factory() as s:
        assert (
            await repo.count_usage(s, "job", dt.datetime(2000, 1, 1, tzinfo=dt.UTC)) == 1
        )  # rejected job not counted
    assert (await harness.run_row(second)).status == "failed"


async def test_agent_run_limit_per_hour(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    steps = fake_pipeline(script={"uses_agent": True})
    h = build_harness(engine, storage, config, steps=steps)
    limits = settings_values(limits={"max_agent_runs_per_hour": 1})
    first = await h.submit(settings=limits)
    # a different idea, otherwise the step cache would reuse every step and no agent run is needed
    second = await h.submit(settings=limits, input_text="Another idea about vacuum and bloat")
    await h.run_all()

    assert [j for j, _ in h.core.results] == [first["job_id"]]
    fail = h.core.fails[0][1]
    assert h.core.fails[0][0] == second["job_id"]
    assert (fail["class"], fail["details"]["code"], fail["details"]["step"]) == (
        "transient",
        "agent_run_rate_limit",
        "script",
    )
    assert 0 < fail["details"]["retry_after"] <= 3600


# ---- cancellation ------------------------------------------------------------------------------


async def test_cancel_stops_a_running_step_and_sends_no_callback(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    gate = Blocker()
    h = build_harness(engine, storage, config, steps=fake_pipeline(capture={"on_run": gate}))
    body = await h.submit()
    await h.worker.run_once()
    await asyncio.wait_for(gate.started.wait(), 5)

    outcome, _ = await h.service.cancel(uuid.UUID(body["job_id"]))
    assert outcome == "cancelling"
    await asyncio.wait_for(h.worker.drain(), 5)  # well inside the 15 s of the spec

    run = await h.run_row(body)
    assert run.status == "cancelled" and run.lease_owner is None
    assert h.core.results == [] and h.core.fails == []
    assert "render" not in await h.step_rows(body)


async def test_cancel_flag_written_by_another_process_is_noticed(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    gate = Blocker()
    h = build_harness(engine, storage, config, steps=fake_pipeline(capture={"on_run": gate}))
    body = await h.submit()
    await h.worker.run_once()
    await asyncio.wait_for(gate.started.wait(), 5)
    run = await h.run_row(body)
    async with h.factory() as s, s.begin():
        await repo.request_cancel(s, run.id)  # no in-process signal: only the database flag
    await asyncio.wait_for(h.worker.drain(), 5)
    assert (await h.run_row(body)).status == "cancelled"
    assert h.core.results == [] and h.core.fails == []


async def test_cancel_before_start_never_runs_a_step(harness: Harness) -> None:
    body = await harness.submit()
    outcome, _ = await harness.service.cancel(uuid.UUID(body["job_id"]))
    assert outcome == "cancelling"
    await harness.run_all()
    assert (await harness.run_row(body)).status == "cancelled"
    assert harness.core.credential_reads == [] and harness.core.progress_calls == []
    assert all(s.calls == 0 for s in harness.steps)


async def test_core_409_on_progress_means_the_job_was_dropped(harness: Harness) -> None:
    harness.core.progress_error = CoreRejected("stale attempt")
    body = await harness.submit()
    await harness.run_all()
    assert (await harness.run_row(body)).status == "cancelled"
    assert harness.core.results == [] and harness.core.fails == []


# ---- recovery ----------------------------------------------------------------------------------


async def test_kill_mid_run_then_restart_resumes_after_the_last_finished_step(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    core = FakeCore()
    gate = Blocker()
    first = build_harness(engine, storage, config, core=core, steps=fake_pipeline(capture={"on_run": gate}))
    body = await first.submit()
    await first.worker.run_once()
    await asyncio.wait_for(gate.started.wait(), 5)

    await first.worker.stop()  # the "kill": tasks are torn down, nothing is marked failed
    run = await first.run_row(body)
    assert run.status == "running" and run.lease_owner is not None
    assert core.results == [] and core.fails == []
    assert (await first.step_rows(body))["capture"].status == "running"

    # a new process starts after the lease has expired
    later = lambda: dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)  # noqa: E731
    second = build_harness(engine, storage, config, core=core, clock=later)
    await second.run_all()

    assert (await second.run_row(body)).status == "succeeded"
    assert len(core.results) == 1 and core.fails == []  # exactly one result callback
    by_name = {s.name: s.calls for s in second.steps}
    assert by_name == {"analysis": 0, "research": 0, "script": 0, "capture": 1, "render": 1, "package": 1}
    assert all(st.status == "succeeded" for st in (await second.step_rows(body)).values())


async def test_run_with_a_live_lease_is_not_taken_over(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    gate = Blocker()
    first = build_harness(engine, storage, config, steps=fake_pipeline(capture={"on_run": gate}))
    await first.submit()
    await first.worker.run_once()
    await asyncio.wait_for(gate.started.wait(), 5)
    second = build_harness(engine, storage, config, core=first.core)
    assert await second.worker.run_once() == []  # lease still valid
    gate.release.set()
    await first.worker.drain()


async def test_undelivered_result_is_re_sent_after_restart_without_redoing_work(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    core = FakeCore()
    core.result_error = CoreUnavailable("core down for 15 minutes")
    first = build_harness(engine, storage, config, core=core)
    body = await first.submit()
    await first.worker.run_once()  # one claim only: the real client has already retried for 15 min
    await first.worker.drain()

    run = await first.run_row(body)
    assert run.status == "running" and run.result is not None  # finished locally, callback missing
    assert run.lease_owner is None  # released so the next claim can retry
    assert core.results == []

    core.result_error = None  # the core is back
    second = build_harness(engine, storage, config, core=core)
    await second.run_all()
    assert (await second.run_row(body)).status == "succeeded"
    assert len(core.results) == 1
    assert core.results[0][1] == run.result  # the very same payload
    assert sum(s.calls for s in second.steps) == 0  # nothing was redone


async def test_lost_lease_stops_the_run_without_callbacks(
    engine: AsyncEngine, storage: Storage, config: BootstrapConfig
) -> None:
    gate = Blocker()
    h = build_harness(engine, storage, config, steps=fake_pipeline(capture={"on_run": gate}))
    body = await h.submit()
    await h.worker.run_once()
    await asyncio.wait_for(gate.started.wait(), 5)
    run = await h.run_row(body)
    far = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    async with h.factory() as s, s.begin():
        assert await repo.take_lease(s, run.id, "other-worker", now=far)  # steals the expired lease
    await asyncio.wait_for(h.worker.drain(), 5)
    assert h.core.results == [] and h.core.fails == []
    assert (await h.run_row(body)).lease_owner == "other-worker"


# ---- step cache --------------------------------------------------------------------------------


async def test_second_attempt_with_identical_inputs_reuses_every_step(harness: Harness) -> None:
    production = uuid.uuid4()
    first = await harness.submit(production_id=production, attempt=1)
    await harness.run_all()
    calls_after_first = [s.calls for s in harness.steps]
    assert calls_after_first == [1] * 6

    second = await harness.submit(production_id=production, attempt=2)
    await harness.run_all()

    assert [s.calls for s in harness.steps] == calls_after_first  # nothing executed again
    rows = await harness.step_rows(second)
    assert {st.status for st in rows.values()} == {"reused"}
    originals = await harness.step_rows(first)
    assert all(rows[n].reused_from == originals[n].id for n in PLAN_NAMES)
    assert len(harness.core.results) == 2  # the second attempt still reports its result
    doc = await harness.service.status_document(uuid.UUID(second["job_id"]))
    assert doc is not None and all(s["reused"] for s in doc["steps"])
    # files of the second attempt point to the first attempt's prefix: no copy
    assert "/video/1/" in harness.core.results[1][1]["output"]["variants"][0]["video"]["ref"]


async def test_changed_idea_text_invalidates_the_cache(harness: Harness) -> None:
    await harness.submit()
    await harness.run_all()
    await harness.submit(input_text="A completely different idea about vacuum")
    await harness.run_all()
    assert [s.calls for s in harness.steps] == [2] * 6


async def test_result_carries_metadata_that_validates_against_the_contract(harness: Harness) -> None:
    from mvideo.contract import StageOutput

    await harness.submit()
    await harness.run_all()
    output = harness.core.results[0][1]["output"]
    parsed = StageOutput.model_validate(output)  # raises when metadata is missing or malformed
    meta = parsed.variants[0].metadata
    assert meta.title and meta.platforms["instagram"].hashtags[0].startswith("#")
    assert output["variants"][0]["post"]["caption"] == meta.platforms["instagram"].caption
