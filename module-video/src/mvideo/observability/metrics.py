"""Prometheus metrics of 03 section 8. One registry per app so tests can create many apps.

`production_id` is never a label: it would explode the cardinality. It goes into logs and spans.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from mvideo import __version__

JOB_BUCKETS = (30, 60, 120, 300, 600, 1200, 2400, 3600, 7200)
STEP_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1200, 2400)
COST_BUCKETS = (0.1, 0.5, 1, 2, 4, 8, 12, 15, 25, 50)
HTTP_BUCKETS = (0.005, 0.025, 0.1, 0.5, 1, 5, 30)


class Metrics:
    def __init__(self) -> None:
        r = self.registry = CollectorRegistry()

        def counter(name: str, doc: str, labels: list[str]) -> Counter:
            return Counter(name, doc, labels, registry=r)

        def gauge(name: str, doc: str, labels: list[str] | None = None) -> Gauge:
            return Gauge(name, doc, labels or [], registry=r)

        def hist(name: str, doc: str, labels: list[str], buckets: tuple[float, ...]) -> Histogram:
            return Histogram(name, doc, labels, buckets=buckets, registry=r)

        gauge("video_build_info", "Module build information", ["version"]).labels(version=__version__).set(1)
        self.jobs = counter("video_jobs", "Finished jobs", ["mode", "status"])
        self.job_duration = hist("video_job_duration_seconds", "Job wall time", ["mode"], JOB_BUCKETS)
        self.step_duration = hist("video_step_duration_seconds", "Step wall time", ["step"], STEP_BUCKETS)
        self.step_failures = counter("video_step_failures", "Failed steps", ["step", "class", "code"])
        self.step_reused = counter("video_step_reused", "Steps served from the cache", ["step"])
        self.schema_retries = counter("video_schema_retries", "Resumes after invalid output", ["step"])
        self.fix_rounds = counter("video_fix_rounds", "Fix rounds after a failed check", ["check"])
        self.blocked = counter("video_blocked", "Blocked steps", ["step"])
        self.agent_turns = hist(
            "video_agent_turns", "Agent turns per run", ["step"], (1, 3, 5, 10, 20, 40, 60)
        )
        self.tokens = counter("video_tokens", "Tokens used", ["step", "kind"])
        self.cost = counter("video_cost_usd", "Cost in USD", ["step", "model", "estimated"])
        self.auth_failures = counter("video_agent_auth_failures", "Agent authentication failures", ["step"])
        self.rate_limited = counter("video_rate_limited", "Claude usage or rate limit hits", ["step"])
        self.jobs_today = gauge("video_jobs_today", "Jobs accepted today (UTC)")
        self.agent_runs_last_hour = gauge("video_agent_runs_last_hour", "Agent runs in the last hour")
        self.job_cost = hist("video_cost_usd_per_job", "Cost of one job", ["mode"], COST_BUCKETS)
        self.egress_denied = counter("video_egress_denied", "Denied egress connections", ["step"])
        self.sandbox_seconds = hist("video_sandbox_seconds", "Sandbox time", ["purpose"], STEP_BUCKETS)
        self.render_ratio = hist(
            "video_render_seconds_per_video_second",
            "Render time per second of video",
            [],
            (0.25, 0.5, 1, 2, 3, 5, 10),
        )
        self.render_frames = counter("video_render_frames", "Frames rendered", [])
        self.check_failures = counter("video_check_failures", "Failed checks", ["check"])
        self.missing_glyphs = counter("video_missing_glyphs", "Missing glyphs", ["role"])
        self.safe_zone = counter("video_safe_zone_violations", "Safe zone violations", [])
        self.duration = hist(
            "video_duration_seconds", "Video length", ["language"], (30, 60, 90, 120, 150, 180, 240)
        )
        self.loudness = hist(
            "video_loudness_lufs", "Integrated loudness", [], (-24, -20, -17, -15, -14, -13, -11, -8)
        )
        self.file_size = hist(
            "video_file_size_bytes", "Final file size", [], (1e6, 5e6, 1e7, 2e7, 5e7, 1e8, 2.5e8)
        )
        self.running = gauge("video_running_jobs", "Runs executing now")
        self.queued = gauge("video_queued_jobs", "Runs waiting for a worker")
        self.http_requests = counter("video_http_requests", "HTTP requests", ["route", "method", "status"])
        self.http_duration = hist(
            "video_http_request_duration_seconds", "HTTP latency", ["route", "method", "status"], HTTP_BUCKETS
        )
        self.core_callback_failures = counter(
            "video_core_callback_failures", "Core callbacks that failed", ["kind"]
        )
