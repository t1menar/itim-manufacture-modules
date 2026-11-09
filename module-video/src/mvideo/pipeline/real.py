"""The real six-step pipeline (05 section 1) and the services its steps need."""

from __future__ import annotations

from typing import Any

from mvideo.pipeline.steps.analysis import AnalysisStep, ResearchStep, ScriptStep
from mvideo.pipeline.steps.base import Step
from mvideo.pipeline.steps.media_steps import CaptureStep, PackageStep, RenderStep, finalize_real


def real_pipeline() -> list[Step]:
    return [AnalysisStep(), ResearchStep(), ScriptStep(), CaptureStep(), RenderStep(), PackageStep()]


__all__ = ["finalize_real", "real_pipeline"]


def services_from_env(sessions: Any, sandbox_mcp_url: str) -> dict[str, Any]:
    """launcher, docker client, git cache and the scratch registry shared by the steps."""
    import os

    from mvideo.agents.launcher import launcher_from_env
    from mvideo.api.mcp_sandbox import ScratchRegistry
    from mvideo.sandbox.executor import make_client
    from mvideo.sources.git_cache import GitCache

    client = make_client()
    return {
        "launcher": launcher_from_env(client),
        "docker": client,
        "git_cache": GitCache(
            client, sessions, os.environ.get("MVIDEO_GIT_IMAGE", "alpine/git"),
            os.environ.get("MVIDEO_AGENT_NETWORK", "video-agent-net"),
        ),
        "scratch": ScratchRegistry(),
        "sandbox_mcp_url": sandbox_mcp_url,
    }  # fmt: skip
