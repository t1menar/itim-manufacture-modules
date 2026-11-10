"""B10: every metric of 03 section 8, cost and usage limits in both cost modes, secrets kept out of logs."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from mvideo.agents.launcher import ReplayLauncher
from mvideo.agents.run import Cost
from mvideo.config import BootstrapConfig
from mvideo.observability import logging as obs_logging
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.analysis import AnalysisStep, ResearchStep
from mvideo.pipeline.steps.fake import fake_pipeline
from mvideo.storage import Storage
from tests.harness import Harness, build_harness
from tests.test_steps import make_ctx, replay

SPEC_METRICS = {  # name as scraped (counters end in _total), type
    "video_jobs_total": "counter", "video_job_duration_seconds": "histogram",
    "video_step_duration_seconds": "histogram", "video_step_failures_total": "counter",
    "video_step_reused_total": "counter", "video_schema_retries_total": "counter",
    "video_fix_rounds_total": "counter", "video_blocked_total": "counter",
    "video_agent_turns": "histogram", "video_tokens_total": "counter", "video_cost_usd_total": "counter",
    "video_agent_auth_failures_total": "counter", "video_rate_limited_total": "counter",
    "video_jobs_today": "gauge", "video_agent_runs_last_hour": "gauge",
    "video_cost_usd_per_job": "histogram", "video_egress_denied_total": "counter",
    "video_sandbox_seconds": "histogram", "video_render_seconds_per_video_second": "histogram",
    "video_render_frames_total": "counter", "video_check_failures_total": "counter",
    "video_missing_glyphs_total": "counter", "video_safe_zone_violations_total": "counter",
    "video_duration_seconds": "histogram", "video_loudness_lufs": "histogram",
    "video_file_size_bytes": "histogram", "video_running_jobs": "gauge", "video_queued_jobs": "gauge",
    "video_http_requests_total": "counter", "video_http_request_duration_seconds": "histogram",
    "video_core_callback_failures_total": "counter",
}  # fmt: skip


@pytest.fixture
def harness(engine: AsyncEngine, storage: Storage, config: BootstrapConfig) -> Harness:
    return build_harness(engine, storage, config)


async def test_metrics_endpoint_lists_every_metric_of_the_spec_after_a_run(harness: Harness) -> None:
    await harness.submit()
    await harness.run_all()
    async with harness.client() as c:
        text = (await c.get("/metrics")).text
    types = dict(re.findall(r"^# TYPE (\S+) (\w+)$", text, re.M))
    for name, kind in SPEC_METRICS.items():
        base = name.removesuffix("_total")  # prometheus_client names a counter without the suffix here
        assert types.get(base) == kind or types.get(name) == kind, name
    assert 'video_jobs_total{mode="create",status="succeeded"} 1.0' in text
    assert "video_jobs_today 1.0" in text and "video_queued_jobs 0.0" in text
    assert 'video_http_requests_total{method="POST",route="/v1/jobs",status="202"}' in text
    assert "production_id" not in text  # never a label


def test_metric_labels_never_include_production_or_job_ids() -> None:
    from mvideo.observability.metrics import Metrics

    for family in Metrics().registry.collect():
        for sample in family.samples:
            assert not {"production_id", "job_id", "run_id"} & set(sample.labels)


async def test_agent_cost_is_added_to_the_run_and_step(harness: Harness) -> None:
    async def bill(ctx) -> None:  # type: ignore[no-untyped-def]
        ctx.usage.append(Cost(0.5, False, 1000, 200, model="m"))

    harness.steps[:] = fake_pipeline(analysis={"on_run": bill, "uses_agent": True})
    harness.runner._steps = harness.steps
    body = await harness.submit()
    await harness.run_all()
    run = await harness.run_row(body)
    assert float(run.cost_usd) == pytest.approx(0.5) and run.tokens_in == 1000 and run.tokens_out == 200
    assert harness.core.results[0][1]["metrics"]["cost_usd"] == pytest.approx(0.5)


# ---- budget, both cost modes --------------------------------------------------------------------


def _ctx(tmp_path: Path, mode: str, budget: float):  # type: ignore[no-untyped-def]
    launcher = ReplayLauncher(tmp_path)
    return make_ctx(launcher, limits={"cost_mode": mode, "job_budget_usd": budget}), launcher


async def test_usd_mode_stops_before_the_run_when_the_budget_is_used_up(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", "analysis.json")
    ctx, launcher = _ctx(tmp_path, "usd", 0.01)
    with pytest.raises(StepError) as e:
        await AnalysisStep().run(ctx)
    assert (e.value.error_class, e.value.code) == ("fatal", "budget_exceeded")
    assert launcher.calls == []  # nothing was started


async def test_usd_mode_gives_the_run_min_of_step_budget_and_remaining(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", "analysis.json")
    ctx, launcher = _ctx(tmp_path, "usd", 0.5)
    await AnalysisStep().run(ctx)
    assert launcher.calls[0].max_budget_usd == pytest.approx(0.5)  # step budget is 1.0
    assert ctx.spent_usd == pytest.approx(0.12) and ctx.usage[0].estimated is False


async def test_usd_mode_second_step_fails_with_budget_exceeded(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", "analysis.json")
    ctx, launcher = _ctx(tmp_path, "usd", 0.2)  # analysis costs 0.12 in the replay, 0.08 is left
    ctx.outputs["analysis"] = await AnalysisStep().run(ctx)
    with pytest.raises(StepError) as e:
        await ResearchStep().run(ctx)
    assert e.value.code == "budget_exceeded" and [c.step for c in launcher.calls] == ["analysis"]


async def test_estimate_mode_enforces_nothing_and_marks_the_cost_estimated(tmp_path: Path) -> None:
    replay(tmp_path, "analysis", "analysis.json")
    ctx, launcher = _ctx(tmp_path, "estimate", 0.01)
    await AnalysisStep().run(ctx)
    assert launcher.calls[0].max_budget_usd is None
    assert ctx.usage[0].estimated is True and ctx.usage[0].usd > 0.01  # computed from tokens


# ---- usage limits -------------------------------------------------------------------------------


async def test_seventh_job_of_the_day_fails_transient_daily_job_limit(harness: Harness) -> None:
    for _ in range(6):
        await harness.submit()
    await harness.run_all(60)
    assert len(harness.core.results) == 6
    await harness.submit()
    await harness.run_all()
    code, klass = harness.core.fails[-1][1]["details"]["code"], harness.core.fails[-1][1]["class"]
    assert (klass, code) == ("transient", "daily_job_limit")
    assert harness.core.fails[-1][1]["details"]["retry_after"] >= 1


async def test_thirteenth_agent_run_in_an_hour_fails_transient_agent_run_rate_limit(harness: Harness) -> None:
    from mvideo.db import repo

    run = None
    body = await harness.submit()
    run = await harness.run_row(body)
    async with harness.factory() as s, s.begin():
        for _ in range(12):
            await repo.log_usage(s, "agent_run", run.id, step="analysis")
    harness.steps[:] = fake_pipeline(analysis={"uses_agent": True})
    harness.runner._steps = harness.steps
    await harness.run_all()
    fail = harness.core.fails[-1][1]
    assert (fail["class"], fail["details"]["code"]) == ("transient", "agent_run_rate_limit")


# ---- secrets ------------------------------------------------------------------------------------

TOKEN = "sk-ant-oat01-0123456789abcdefghijklmnop"


def _capture(fn) -> str:  # type: ignore[no-untyped-def]
    buf = io.StringIO()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level, obs_logging.add_fields, obs_logging.redact,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )  # fmt: skip
    fn(structlog.get_logger())
    return buf.getvalue()


def test_secret_values_and_sensitive_keys_never_reach_the_log() -> None:
    obs_logging.register_secret("plain-credential-value")
    try:
        out = _capture(
            lambda log: log.info(
                "event plain-credential-value", token=TOKEN, api_key="x1", Authorization="Bearer abc",
                nested={"oauth_token": "zzz", "note": f"has {TOKEN} inside plain-credential-value"},
                items=["plain-credential-value"],
            )
        )  # fmt: skip
    finally:
        obs_logging.forget_secret("plain-credential-value")
    for leaked in (TOKEN, "plain-credential-value", "Bearer abc", "zzz", "x1"):
        assert leaked not in out, leaked
    assert json.loads(out)["service"] == "video"


async def test_job_run_leaves_no_credential_in_the_logs(
    harness: Harness, capfd: pytest.CaptureFixture[str]
) -> None:
    harness.core.credential_value = TOKEN  # the FakeCore hands this out
    await harness.submit()
    await harness.run_all()
    captured = capfd.readouterr()
    assert TOKEN not in captured.out + captured.err
