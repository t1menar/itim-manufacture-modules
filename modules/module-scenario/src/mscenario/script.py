"""Script phase: from the idea and the verified research to a scenario and a post.

Same policy as the research phase. The idea decides the content and the limits (brief, constraints,
instructions); this module only checks, deterministically and for free, that the result is renderable and honest:
schema, every code line against the pinned commit, no typed numbers, explained terms, caption fit, duration.
A reviewer's comment arrives as a `Revision` with the previous script: the agent rewrites, the same checks run.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mscenario import agent as ag
from mscenario.db import transaction
from mscenario.issues import Issue
from mscenario.models import ScriptResult
from mscenario.rules import RuleConfig, check_script
from mscenario.service import BudgetExceeded, Outcome, ResearchInvalid, ResearchSettings
from mscenario.sources import SourceTree
from mscenario.verify import schema_issues

MAX_ISSUES = 20
POST_CAPTION_MAX = 2200


class ScriptService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        agent: ag.ScriptAgent,
        settings: ResearchSettings | None = None,
    ) -> None:
        self.sm, self.agent, self.cfg = sm, agent, settings or ResearchSettings()

    async def run(
        self,
        idea: dict[str, Any],
        research: dict[str, Any],
        step_key: str,
        tree: SourceTree | None,
        revision: ag.Revision | None = None,
    ) -> Outcome:
        async with transaction(self.sm) as s:
            stored = await s.get(ScriptResult, step_key)
            if stored is not None:
                return Outcome(stored.status, stored.document, ag.Usage(Decimal(stored.cost_usd)), 0)

        rules = RuleConfig.from_idea(idea)
        usage = ag.Usage()
        issues: list[dict[str, str]] = []
        for attempt in range(self.cfg.schema_retries + 1):
            remaining = self.cfg.budget_usd - usage.cost_usd
            if attempt > 0 and remaining < self.cfg.min_attempt_budget_usd:
                raise BudgetExceeded(usage.cost_usd, self.cfg.budget_usd)
            resp = await self.agent.run(
                ag.ScriptRequest(
                    idea=idea, research=research, source_root=tree.root if tree else None,
                    schema_hint=ag.SCRIPT_HINT, attempt=attempt, previous_issues=issues, revision=revision,
                    max_budget_usd=remaining, model=self.cfg.model,
                )
            )  # fmt: skip
            usage = usage + resp.usage
            found = self._check(resp.output, research, tree, rules, revision)
            if isinstance(found, dict):
                status = "blocked" if "reason" in found else "done"
                doc = (
                    {"format": "manufacture.script.blocked/1", "idea_ref": idea["idea_ref"], **found}
                    if status == "blocked"
                    else found
                )
                await self._store(step_key, idea, revision, status, doc, usage)
                return Outcome(status, doc, usage, attempt + 1)
            issues = [i.as_dict() for i in found[:MAX_ISSUES]]
        raise ResearchInvalid(issues)

    async def _store(
        self, step_key: str, idea: dict[str, Any], revision: ag.Revision | None, status: str, doc: dict[str, Any],
        usage: ag.Usage,
    ) -> None:  # fmt: skip
        async with transaction(self.sm) as s:
            s.add(
                ScriptResult(
                    step_key=step_key,
                    idea_ref=str(idea["idea_ref"]),
                    visit=revision.visit if revision else 1,
                    status=status,
                    document=doc,
                    cost_usd=usage.cost_usd,
                    usage=usage.as_dict(),
                )  # fmt: skip
            )

    def _check(
        self,
        out: dict[str, Any],
        research: dict[str, Any],
        tree: SourceTree | None,
        rules: RuleConfig,
        revision: ag.Revision | None,
    ) -> dict[str, Any] | list[Issue]:
        if "blocked" in out:
            blocked = out["blocked"]
            if not isinstance(blocked, dict) or not blocked.get("reason"):
                return [Issue("schema", "/blocked", "blocked needs a reason")]
            return {k: blocked[k] for k in ("reason", "missing", "suggestion") if k in blocked}
        if set(out) - {"script", "post"} or "script" not in out or "post" not in out:
            return [Issue("schema", "/", 'write {"script": ..., "post": ...} or {"blocked": ...}')]
        script, post = _normalize(out["script"], str(research.get("idea_ref", ""))), out["post"]
        issues = [Issue("schema", f"/script{i.path}", i.message, "script") for i in schema_issues("scenario", script)]
        issues += [Issue("schema", f"/post{i.path}", i.message, "post") for i in schema_issues("post", post)]
        if issues:
            return issues
        commit = research.get("commit")
        meta_commit = ((script.get("meta") or {}).get("system") or {}).get("commit")
        if commit and meta_commit != commit:
            issues.append(Issue("schema", "/script/meta/system/commit", f"must equal the research commit {commit}"))
        if tree is None and commit:
            issues.append(Issue("sources_known", "/script", "a pinned source tree is required to check code lines"))
        issues += check_script(script, research=research, source=tree, cfg=rules, file="script")
        issues += _check_post(post)
        if revision is not None:
            if script == revision.previous_script and post == revision.previous_post:
                issues.append(Issue("revise", "/", "nothing changed, but the reviewer asked for changes"))
        return issues if issues else {"script": script, "post": post}


def _normalize(script: Any, idea_ref: str) -> Any:  # noqa: ANN401
    """Fill what the platform knows and agents keep getting wrong, instead of spending retries on it.

    `meta.idea_id` is the integer of `idea:<id>:v<n>`; an empty `captures` list means no captures (`{}`);
    `facts` defaults to none (a script without facts is valid when the research had none).
    """
    if not isinstance(script, dict):
        return script
    out = dict(script)
    m = re.fullmatch(r"idea:([0-9]+):v[0-9]+", idea_ref)
    if isinstance(out.get("meta"), dict) and m:
        out["meta"] = {**out["meta"], "idea_id": int(m.group(1))}
    if out.get("captures") in ([], None):
        out["captures"] = {}
    out.setdefault("facts", [])
    return out


def _check_post(post: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    if len(post["hook"]) + len(post["summary"]) > POST_CAPTION_MAX:
        out.append(Issue("post", "/post/summary", f"hook and summary together exceed {POST_CAPTION_MAX} characters"))
    return out
