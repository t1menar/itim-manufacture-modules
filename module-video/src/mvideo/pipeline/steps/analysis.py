"""Steps analysis, research and script (05 sections 2.2 to 2.4)."""

from __future__ import annotations

from typing import Any

from mvideo.pipeline.context import RunContext
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.agent_step import (
    AgentStep,
    channel_json,
    common_values,
    environment_json,
    jdump,
    limits_json,
)  # fmt: skip
from mvideo.validate.issues import Issue


class AnalysisStep(AgentStep):
    name = "analysis"
    lo, hi = 0, 5
    produces = ("analysis.json",)
    settings_keys = ("sandbox_images", "sources", "video", "prompt_versions")

    async def inputs(self, ctx: RunContext) -> dict[str, bytes]:
        return {
            "idea.json": jdump(ctx.input.idea.model_dump()),
            "environment.json": jdump(environment_json(ctx)),
            "channel.json": jdump(channel_json(ctx)),
        }

    async def values(self, ctx: RunContext) -> dict[str, Any]:
        v = common_values(ctx)
        keys = ", ".join(
            f"{k} ({i.description})" if i.description else k for k, i in ctx.settings.sandbox_images.items()
        )
        return {k: v[k] for k in ("idea_id", "idea_text", "channel_name", "min_s", "max_s")} | {
            "sandbox_keys": keys
        }

    def extra_checks(self, ctx: RunContext, docs: dict[str, Any]) -> list[Issue]:
        a = docs.get("analysis.json")
        if not a or a.get("__unreadable__"):
            return []
        s = ctx.settings
        issues = []
        system = a.get("system", {})
        allowed = {(r.url, ref) for r in s.sources.allowed_repos for ref in r.refs}
        if (system.get("repo"), system.get("ref")) not in allowed:
            issues.append(
                Issue(
                    "analysis", "/system", "repo and ref must be listed in environment.json", "analysis.json"
                )
            )
        if a.get("sandbox_image") not in s.sandbox_images:
            issues.append(
                Issue("analysis", "/sandbox_image", "image key is not in environment.json", "analysis.json")
            )
        return issues


class ResearchStep(AgentStep):
    name = "research"
    lo, hi = 5, 20
    produces = ("research.json",)
    settings_keys = ("sources", "prompt_versions", "network")

    async def inputs(self, ctx: RunContext) -> dict[str, bytes]:
        return {
            "idea.json": jdump(ctx.input.idea.model_dump()),
            "analysis.json": await ctx.storage.get_bytes(ctx.outputs["analysis"]["analysis.json"].ref),
        }

    async def pin(self, ctx: RunContext) -> tuple[str, str, str]:
        a = await self.read_json(ctx, "analysis", "analysis.json")
        system = a["system"]
        commit = system.get("commit")
        if not commit:
            if ctx.git_cache is None:
                raise StepError("fatal", "internal", "no source cache to pin the commit", step=self.name)
            commit = await ctx.git_cache.resolve_commit(ctx.settings, system["repo"], system["ref"])
        return system["repo"], system["ref"], commit

    async def values(self, ctx: RunContext) -> dict[str, Any]:
        repo, ref, commit = await self.pin(ctx)
        return {"idea_text": ctx.input.idea.text, "repo": repo, "ref": ref, "commit": commit}

    async def src_volume(self, ctx: RunContext) -> str | None:
        repo, _, commit = await self.pin(ctx)
        return None if ctx.git_cache is None else await ctx.git_cache.ensure(ctx.settings, repo, commit)


class ScriptStep(AgentStep):
    name = "script"
    lo, hi = 20, 35
    produces = ("script.en.json",)
    settings_keys = ("video", "text", "timing", "palette", "prompt_versions", "limits")

    async def inputs(self, ctx: RunContext) -> dict[str, bytes]:
        get = ctx.storage.get_bytes
        return {
            "idea.json": jdump(ctx.input.idea.model_dump()),
            "analysis.json": await get(ctx.outputs["analysis"]["analysis.json"].ref),
            "research.json": await get(ctx.outputs["research"]["research.json"].ref),
            "channel.json": jdump(channel_json(ctx)),
            "limits.json": jdump(limits_json(ctx)),
        }

    async def values(self, ctx: RunContext) -> dict[str, Any]:
        v = common_values(ctx)
        research = await self.read_json(ctx, "research", "research.json")
        return {k: v[k] for k in ("channel_name", "idea_text", "min_s", "max_s", "reading_wps")} | {
            "commit": research["commit"],
            "fix_report": ctx.fix_reports.get("script", ""),
        }

    async def src_volume(self, ctx: RunContext) -> str | None:
        if ctx.git_cache is None:
            return None
        a = await self.read_json(ctx, "analysis", "analysis.json")
        research = await self.read_json(ctx, "research", "research.json")
        return await ctx.git_cache.ensure(ctx.settings, a["system"]["repo"], research["commit"])
