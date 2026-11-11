"""Manufacture platform adapter: the `video` step as an SDK module (`mf-module run mvgen.adapter:app`).

Input: the idea document and the approved scenario (`research`, `script`, `post`); optionally the previous plan and
capture. Output: the finished variant with refs to video, cover and contact sheet. `step_key = ctx.step_key` (one per
visit, contract 0.3.0). The capture cache already reuses a recorded session when the commands did not change, so a
pipeline normally passes no `previous`. The cost of the attempt goes to the platform as `usage`.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from manufacture import Context, Fatal, Module, NeedsAttention, Transient
from pydantic import BaseModel, Field

from mvgen.service import GenerationService, Previous
from mvgen.store import StoreError


class PreviousIn(BaseModel):
    plan: dict[str, Any]
    capture: dict[str, Any]


class StepIn(BaseModel):
    idea: dict[str, Any]
    scenario: dict[str, Any]  # {research, script, post}
    channel: dict[str, Any] = Field(default_factory=dict)  # caption_template, hashtags
    previous: PreviousIn | None = None


class StepOut(BaseModel):
    variants: list[dict[str, Any]]
    capture: dict[str, Any]
    cost_usd: str


Provider = Callable[[], Awaitable[GenerationService]]
# failed-result codes that an operator can fix (edit the idea, the image or the budget); the rest are final
ATTENTION = {"version_mismatch", "not_reproducible", "budget_exceeded"}


def make_app(provider: Provider, name: str = "video-generation", version: str = "0.1.0") -> Module[Any]:
    app = Module(name, version=version, concurrency=1)

    @app.step(input=StepIn, output=StepOut)
    async def handle(ctx: Context[Any], inp: StepIn) -> StepOut:
        svc = await provider()
        key = ctx.step_key
        prev = Previous(inp.previous.plan, inp.previous.capture) if inp.previous else None
        await ctx.progress(0.05, "capture")
        try:
            out = await svc.run(inp.idea, inp.scenario, key, channel=inp.channel, previous=prev)
        except StoreError as e:
            raise Transient(str(e), code="store_unavailable", retry_after_s=30) from e
        if out.status != "done":
            doc = out.document
            msg = f"{doc['code']}: {doc['message']}"
            if doc["code"] in ATTENTION:
                raise NeedsAttention(msg, code=doc["code"])
            raise Fatal(msg, code=doc["code"])
        d = out.document
        usage = out.usage
        models: dict[str | None, dict[str, int]] = dict(usage.tokens.items()) if usage.tokens else {None: {}}
        for i, (model, t) in enumerate(models.items()):
            ctx.add_usage(
                float(usage.cost_usd) if i == 0 else 0.0, model=model,
                input_tokens=t.get("input", 0), output_tokens=t.get("output", 0),
                cache_read=t.get("cache_read", 0), cache_write=t.get("cache_write", 0),
            )  # fmt: skip
        return StepOut(variants=d["variants"], capture=d["capture"], cost_usd=str(out.usage.cost_usd))

    return app


_service: GenerationService | None = None


async def _from_env() -> GenerationService:
    """Production wiring (`MVGEN_*`): Postgres, Claude planner, Docker runner, MinIO (`S3_*`) or local store."""
    global _service  # noqa: PLW0603
    if _service is None:
        from pathlib import Path  # noqa: PLC0415

        from mvgen.capture import CaptureService  # noqa: PLC0415
        from mvgen.claude_planner import ClaudeCapturePlanner  # noqa: PLC0415
        from mvgen.db import make_engine, make_sessionmaker  # noqa: PLC0415
        from mvgen.sandbox.config import SandboxCatalog  # noqa: PLC0415
        from mvgen.sandbox.runner import DockerCaptureRunner  # noqa: PLC0415
        from mvgen.store import ArtifactStore, LocalStore, S3Store  # noqa: PLC0415
        from mvgen.trees import GitTrees  # noqa: PLC0415

        sm = make_sessionmaker(make_engine(os.environ["MVGEN_DATABASE_URL"]))
        catalog = SandboxCatalog.load(os.environ["MVGEN_SANDBOX_CATALOG"])
        captures = CaptureService(
            sm,
            ClaudeCapturePlanner(model=os.environ.get("MVGEN_MODEL")),
            DockerCaptureRunner(catalog),
            describe=catalog.describe,
        )
        store: ArtifactStore
        if os.environ.get("S3_ENDPOINT"):
            from mf_storage.client import StorageClient, StorageConfig  # noqa: PLC0415

            client = StorageClient(StorageConfig.from_mapping(dict(os.environ)))
            client.ensure_bucket()
            store = S3Store(client)
        else:
            store = LocalStore(Path(os.environ.get("MVGEN_STORE_DIR", "/var/lib/mvgen/store")))
        _service = GenerationService(sm, captures, GitTrees(), store)
    return _service


app = make_app(_from_env)

__all__ = ["StepIn", "StepOut", "app", "make_app"]
