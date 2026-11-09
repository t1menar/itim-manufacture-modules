"""Base of the Claude steps: workspace, run, blocked handling, validation with resume (05 sections 2.8, 4)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from mvideo.agents import prompts
from mvideo.agents.launcher import AgentRequest, AgentResult
from mvideo.agents.run import run_agent
from mvideo.agents.workspace import Workspace
from mvideo.pipeline.context import RunContext
from mvideo.pipeline.errors import StepError
from mvideo.pipeline.steps.base import Step
from mvideo.storage import Artifact
from mvideo.validate.issues import Issue
from mvideo.validate.rules import RuleConfig
from mvideo.validate.runner import validate_documents

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "validate" / "schemas"
REFERENCE_DIR = Path(__file__).resolve().parents[4] / "reference" / "create_database"
BLOCKED_CODE = {
    "analysis": "idea_not_showable", "research": "facts_missing", "script": "facts_missing",
    "capture": "not_reproducible", "package": "facts_missing", "script-revise": "facts_missing",
}  # fmt: skip
RESUME_PROMPT = (
    "The validator found these errors in /out/{files}. Fix exactly these and run validate again. "
    "The full report is in /in/validation_errors.json."
)


def reference_files() -> dict[str, bytes]:
    """`/ref/create_database/*.json`: the reference scenario the prompts point at."""
    return {f"create_database/{p.name}": p.read_bytes() for p in sorted(REFERENCE_DIR.glob("*.json"))}


def schema_files() -> dict[str, bytes]:
    """`/work/schemas/*.schema.json`."""
    return {f"schemas/{p.name}": p.read_bytes() for p in sorted(SCHEMA_DIR.glob("*.schema.json"))}


def jdump(obj: Any) -> bytes:
    return json.dumps(obj, indent=1, ensure_ascii=False).encode()


def environment_json(ctx: RunContext) -> dict[str, Any]:
    s = ctx.settings
    return {
        "sandbox_images": {
            k: {
                "description": v.description,
                "version_expect": v.version_expect,
                "sessions": list(v.sessions),
            }
            for k, v in s.sandbox_images.items()
        },
        "allowed_repos": [r.model_dump(mode="json") for r in s.sources.allowed_repos],
        "duration_s": s.video.duration_s.model_dump(),
    }


def channel_json(ctx: RunContext) -> dict[str, Any]:
    ch = ctx.input.channels[0]
    return {"id": ch.id, "name": ch.name or ch.id, "language": ch.language,
            "settings": ch.settings.model_dump(exclude_none=True) if ch.settings else {}}  # fmt: skip


def limits_json(ctx: RunContext) -> dict[str, Any]:
    s = ctx.settings
    return {"duration_s": s.video.duration_s.model_dump(), "text": s.text.model_dump(mode="json"),
            "timing": s.timing.model_dump(), "reading_wps": reading_wps(ctx)}  # fmt: skip


def reading_wps(ctx: RunContext) -> float:
    st = ctx.input.channels[0].settings
    return float(st.reading_wps) if st and st.reading_wps else 3.5  # 04 section 2.3


def common_values(ctx: RunContext) -> dict[str, Any]:
    ch = ctx.input.channels[0]
    d = ctx.settings.video.duration_s
    return {
        "idea_id": ctx.input.idea.id, "idea_text": ctx.input.idea.text, "channel_name": ch.name or ch.id,
        "min_s": int(d.min), "max_s": int(d.max), "reading_wps": reading_wps(ctx),
    }  # fmt: skip


def parse_docs(files: dict[str, bytes]) -> dict[str, Any]:
    docs: dict[str, Any] = {}
    for name, data in files.items():
        if name.endswith(".json") and not name.startswith("_"):
            try:
                docs[name] = json.loads(data)
            except ValueError:
                docs[name] = {"__unreadable__": True}
    return docs


def _file_version(ref: str) -> str:
    """Without a store `active` is the packaged 1.0.0 (tests calling a step directly)."""
    return "1.0.0" if ref == "active" else ref


class AgentStep(Step):
    """One Claude invocation that writes `produces` into /out, with validation and resume."""

    uses_agent = True
    produces: tuple[str, ...] = ()  # files that must exist (unless blocked.json)
    source_needed = False

    # -- hooks -------------------------------------------------------------------------------------
    async def inputs(self, ctx: RunContext) -> dict[str, bytes]:
        raise NotImplementedError

    async def values(self, ctx: RunContext) -> dict[str, Any]:
        """Placeholder values of task.md."""
        raise NotImplementedError

    async def src_volume(self, ctx: RunContext) -> str | None:
        return None

    def extra_checks(self, ctx: RunContext, docs: dict[str, Any]) -> list[Issue]:
        return []

    # -- machinery ---------------------------------------------------------------------------------
    async def prepare(self, ctx: RunContext) -> None:
        """Resolve the prompt and the skill (`active` means the version activated in the module)."""
        store = ctx.prompts or prompts.PromptStore()
        for key in (self.name, "skill"):
            ctx.prompt_cache[key] = await store.get(key, ctx.settings.prompt_versions.get(key, "active"))

    def request(self, ctx: RunContext, inputs: dict[str, bytes], values: dict[str, Any]) -> AgentRequest:
        p = ctx.prompt_cache.get(self.name) or prompts.load_prompt(
            self.name, _file_version(ctx.settings.prompt_versions.get(self.name, "active"))
        )
        task = prompts.render(p.task_md, values)
        skill_prompt = ctx.prompt_cache.get("skill")
        skill = (
            skill_prompt.claude_md
            if skill_prompt
            else prompts.load_skill(_file_version(ctx.settings.prompt_versions.get("skill", "active")))
        )
        ws = Workspace.build(
            claude_md=p.claude_md, task_md=task, skill_md=skill, inputs=inputs, ref=reference_files()
        )
        ws.work.update(schema_files())
        return AgentRequest(
            self.name, f"{ctx.run_id.hex[:12]}-{self.name}", ctx.settings, ws, task,
            credential=ctx.credential, reading_wps=reading_wps(ctx),
            settings_values=ctx.settings.model_dump(mode="json"),
        )  # fmt: skip

    def validate(self, ctx: RunContext, inputs: dict[str, bytes], out: dict[str, bytes]) -> list[Issue]:
        docs = {**parse_docs(inputs), **parse_docs(out)}
        report = validate_documents(
            docs, source=ctx.source, cfg=RuleConfig.from_settings(ctx.settings.model_dump(mode="json"))
        )
        produced = set(parse_docs(out))
        issues = [i for i in report.issues if i.file in produced or not i.file]
        return issues + self.extra_checks(ctx, docs)

    def blocked_error(self, out: dict[str, bytes]) -> StepError:
        info = json.loads(out["blocked.json"]) if out.get("blocked.json") else {}
        return StepError(
            "blocked", BLOCKED_CODE[self.name],
            info.get("reason", "the agent could not do the step honestly"), step=self.name,
            details={"missing": info.get("missing", []), "suggestion": info.get("suggestion")},
        )  # fmt: skip

    async def agent_loop(
        self, ctx: RunContext, req: AgentRequest, inputs: dict[str, bytes]
    ) -> tuple[AgentResult, dict[str, bytes]]:
        """Run, validate, resume with the validator output up to `limits.schema_retries` times."""
        retries = ctx.settings.limits.schema_retries
        for attempt in range(retries + 1):
            res, _, cost = await run_agent(ctx.launcher, req)
            ctx.usage.append(cost)
            out = {k: v for k, v in res.files.items() if not k.startswith("_")}
            if "blocked.json" in out:
                raise self.blocked_error(out)
            missing = [f for f in self.produces if f not in out]
            issues = self.validate(ctx, inputs, out)
            if not missing and not issues:
                return res, out
            report = [i.as_dict() for i in issues] + [
                {"message": f"/out/{f} was not written"} for f in missing
            ]
            if attempt == retries:
                raise StepError(
                    "fatal", "schema_invalid", f"{self.name} output invalid after {retries} resumes",
                    step=self.name, details={"issues": report[:20]},
                )  # fmt: skip
            inputs = {**inputs, "validation_errors.json": jdump(report)}
            ws = dataclasses.replace(req.workspace, inputs=inputs)
            req = dataclasses.replace(
                req, workspace=ws, resume=res.result.get("session_id"),
                prompt=RESUME_PROMPT.format(files=", ".join(self.produces)),
            )  # fmt: skip
        raise AssertionError("unreachable")

    async def upload(self, ctx: RunContext, files: dict[str, bytes]) -> dict[str, Artifact]:
        out: dict[str, Artifact] = {}
        for name, data in files.items():
            kind = "json" if name.endswith(".json") else "text"
            out[name] = await ctx.storage.put_bytes(ctx.key(self.name, name), data, kind=kind)
        return out

    async def run(self, ctx: RunContext) -> dict[str, Artifact]:
        inputs = await self.inputs(ctx)
        req = self.request(ctx, inputs, await self.values(ctx))
        req.src_volume = await self.src_volume(ctx)
        res, out = await self.agent_loop(ctx, req, inputs)
        transcript = res.files.get("_transcript.jsonl", b"")
        artifacts = await self.upload(ctx, {k: v for k, v in out.items() if k != "blocked.json"})
        artifacts["_transcript.jsonl"] = await ctx.storage.put_bytes(
            ctx.key(self.name, "_transcript.jsonl"), transcript, kind="text"
        )
        return artifacts

    # -- helpers for subclasses ---------------------------------------------------------------------
    async def read_json(self, ctx: RunContext, step: str, name: str) -> Any:
        files = ctx.files(step) if step == "script" else ctx.outputs[step]
        return json.loads(await ctx.storage.get_bytes(files[name].ref))
