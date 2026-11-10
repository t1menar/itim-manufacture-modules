"""ResearchService: pin the source, reuse cached facts, run the agent, verify, assemble, remember.

Token and cost policy lives here, not in prompts:
- the source is pinned by code (repo allowlist, commit), the agent never chooses it;
- cached facts for (system, commit) are given to the agent, which writes only the delta;
- citations are verified deterministically, so a wrong quote costs one cheap retry with exact errors;
- retries are capped and bounded by a USD budget; a blocked idea stops immediately and is not retried;
- a retried platform step returns the stored result and spends nothing.
No database transaction is held while the agent runs.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mscenario import agent as ag
from mscenario.cache import KnowledgeCache, idea_terms
from mscenario.db import transaction
from mscenario.issues import Issue
from mscenario.models import KnowledgeFact, ResearchResult
from mscenario.sources import Pin, SourceError, SourceProvider, SourceTree, allowed_pin_source, normalize_repo
from mscenario.verify import check_document, check_facts, schema_issues

DEFAULT_DOMAINS = ("github.com", "raw.githubusercontent.com", "stackoverflow.com", "news.ycombinator.com")
MAX_ISSUES = 20
ID_RE = re.compile(r"^f([0-9]+)$")


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    schema_retries: int = 2
    budget_usd: Decimal = Decimal("1.5")
    min_attempt_budget_usd: Decimal = Decimal("0.1")
    cache_limit: int = 15
    cache_max_chars: int = 3000
    allowed_domains: tuple[str, ...] = DEFAULT_DOMAINS
    model: str | None = None


class BudgetExceeded(Exception):
    def __init__(self, spent: Decimal, budget: Decimal) -> None:
        super().__init__(f"research budget exceeded: spent {spent} of {budget} USD")
        self.spent, self.budget = spent, budget


class ResearchInvalid(Exception):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        super().__init__(f"research output is still invalid after retries: {issues[:3]}")
        self.issues = issues


class SourceNotAllowed(Exception):
    pass


@dataclass(slots=True)
class Outcome:
    status: str  # done | blocked
    document: dict[str, Any]
    usage: ag.Usage = field(default_factory=ag.Usage)
    attempts: int = 0


def choose_source(idea: Mapping[str, Any]) -> tuple[str, str] | None:
    """(repo, ref) the research is pinned to: an explicit source_ref of the idea, else the environment default."""
    for ref in idea.get("source_refs") or []:
        if isinstance(ref, dict) and ref.get("kind", "repo") == "repo" and ref.get("repo"):
            return str(ref["repo"]), str(ref.get("ref") or "HEAD")
    env = idea.get("environment") or {}
    for entry in env.get("allowed_repos") or []:
        if isinstance(entry, str):
            return entry, "HEAD"
        if isinstance(entry, dict) and entry.get("repo"):
            refs = entry.get("refs") or []
            return str(entry["repo"]), str(refs[0] if refs else "HEAD")
    return None


class ResearchService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        sources: SourceProvider,
        agent: ag.ResearchAgent,
        settings: ResearchSettings | None = None,
        url_quote_ok: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.sm, self.sources, self.agent = sm, sources, agent
        self.cfg, self.url_quote_ok = settings or ResearchSettings(), url_quote_ok

    async def run(
        self,
        idea: dict[str, Any],
        step_key: str,
        pinned: tuple[Pin | None, SourceTree | None] | None = None,
    ) -> Outcome:
        async with transaction(self.sm) as s:
            stored = await s.get(ResearchResult, step_key)
            if stored is not None:
                return Outcome(stored.status, stored.document, ag.Usage(Decimal(stored.cost_usd)), 0)

        pin, tree = pinned if pinned is not None else await self.pin(idea)
        system = normalize_repo(pin.repo) if pin else None
        cached: list[KnowledgeFact] = []
        if pin and system:
            async with transaction(self.sm) as s:
                cached = list(
                    await KnowledgeCache(s).relevant(
                        system, pin.commit, idea_terms(idea),
                        limit=self.cfg.cache_limit, max_chars=self.cfg.cache_max_chars,
                    )
                )  # fmt: skip
        by_id = {f"f{i}": row for i, row in enumerate(cached, start=1)}
        outcome, delta = await self._attempts(idea, pin, tree, by_id)

        async with transaction(self.sm) as s:
            if outcome.status == "done" and pin and system:
                cache = KnowledgeCache(s)
                await cache.store(system, pin.commit, [f for f in delta["facts"]])
                used = [by_id[i] for i in delta.get("reused_facts", []) if i in by_id]
                await cache.touch([await s.merge(r) for r in used])
            s.add(
                ResearchResult(
                    step_key=step_key,
                    idea_ref=str(idea["idea_ref"]),
                    status=outcome.status,
                    document=outcome.document,
                    cost_usd=outcome.usage.cost_usd,
                    usage=outcome.usage.as_dict(),
                )  # fmt: skip
            )
        return outcome

    async def pin(self, idea: Mapping[str, Any]) -> tuple[Pin | None, SourceTree | None]:
        choice = choose_source(idea)
        if choice is None:
            return None, None
        repo, ref = choice
        allowed = (idea.get("environment") or {}).get("allowed_repos") or []
        if not allowed_pin_source(repo, ref, allowed) and not (
            ref == "HEAD" and allowed_pin_source(repo, "HEAD", allowed)
        ):
            raise SourceNotAllowed(f"{repo}@{ref} is not in the allowed repositories of the environment")
        try:
            return await self.sources.checkout(repo, ref)
        except SourceError as e:
            raise SourceNotAllowed(str(e)) from e

    async def _attempts(
        self, idea: dict[str, Any], pin: Pin | None, tree: SourceTree | None, by_id: dict[str, KnowledgeFact]
    ) -> tuple[Outcome, dict[str, Any]]:
        cached = [ag.CachedFact(i, r.text, dict(r.cite)) for i, r in by_id.items()]
        first_new = len(by_id) + 1
        usage = ag.Usage()
        issues: list[dict[str, str]] = []
        for attempt in range(self.cfg.schema_retries + 1):
            remaining = self.cfg.budget_usd - usage.cost_usd
            if attempt > 0 and remaining < self.cfg.min_attempt_budget_usd:
                raise BudgetExceeded(usage.cost_usd, self.cfg.budget_usd)
            resp = await self.agent.run(
                ag.AgentRequest(
                    idea=idea, source_root=tree.root if tree else None, commit=pin.commit if pin else None,
                    cached_facts=cached, first_new_id=first_new, allowed_domains=list(self.cfg.allowed_domains),
                    schema_hint=ag.SCHEMA_HINT, attempt=attempt, previous_issues=issues,
                    max_budget_usd=remaining, model=self.cfg.model,
                )
            )  # fmt: skip
            usage = usage + resp.usage
            delta = resp.output
            found = self._check(delta, idea, pin, tree, by_id)
            if isinstance(found, Outcome):  # blocked, or a finished document
                found.usage, found.attempts = usage, attempt + 1
                return found, delta
            issues = [i.as_dict() for i in found[:MAX_ISSUES]]
        raise ResearchInvalid(issues)

    def _check(
        self, delta: dict[str, Any], idea: dict[str, Any], pin: Pin | None, tree: SourceTree | None,
        by_id: dict[str, KnowledgeFact],
    ) -> Outcome | list[Issue]:  # fmt: skip
        bad = schema_issues("delta", delta)
        if bad:
            return bad
        feas = delta["feasibility"]
        if feas["decision"] == "blocked":
            return Outcome(
                "blocked", {"format": "manufacture.research.blocked/1", "idea_ref": idea["idea_ref"], **feas}
            )
        issues: list[Issue] = []
        new = delta.get("facts", [])
        reused = delta.get("reused_facts", [])
        for fid in reused:
            if fid not in by_id:
                issues.append(
                    Issue("research", "/reused_facts", f"{fid} is not one of the cached facts you were given")
                )
        new_ids = [f["id"] for f in new]
        for fid in new_ids:
            if fid in by_id or new_ids.count(fid) > 1:
                issues.append(
                    Issue("research", "/facts", f"id {fid} is already taken; new ids start after the cached ones")
                )
        issues += check_facts(new, tree, self.cfg.allowed_domains, self.url_quote_ok)
        doc = self._assemble(delta, idea, pin, by_id)
        issues += schema_issues("research", doc)
        if not issues:
            issues += check_document(doc, tree)
        return issues if issues else Outcome("done", doc)

    @staticmethod
    def _assemble(
        delta: Mapping[str, Any], idea: Mapping[str, Any], pin: Pin | None, by_id: Mapping[str, KnowledgeFact]
    ) -> dict[str, Any]:
        facts = [
            {"id": i, "text": by_id[i].text, "cite": dict(by_id[i].cite), "origin": "cache"}
            for i in delta.get("reused_facts", [])
            if i in by_id
        ]
        facts += [{**f, "origin": "new"} for f in delta.get("facts", [])]
        facts.sort(key=lambda f: int(ID_RE.match(f["id"]).group(1)))  # type: ignore[union-attr]
        return {
            "format": "manufacture.research/2",
            "idea_ref": idea["idea_ref"],
            "system": {"repo": pin.repo, "ref": pin.ref} if pin else None,
            "commit": pin.commit if pin else None,
            "viewer_questions": delta.get("viewer_questions", []),
            "misconceptions": delta.get("misconceptions", []),
            "call_path": delta.get("call_path", []),
            "facts": facts,
            "terms": delta.get("terms", []),
            "capture_needs": delta.get("capture_needs", []),
            "knowledge": {
                "cache_hits": len([f for f in facts if f["origin"] == "cache"]),
                "new_facts": len([f for f in facts if f["origin"] == "new"]),
            },
        }


__all__ = [
    "BudgetExceeded", "Outcome", "ResearchInvalid", "ResearchService", "ResearchSettings", "SourceNotAllowed",
    "choose_source",
]  # fmt: skip
