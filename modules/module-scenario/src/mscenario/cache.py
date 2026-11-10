"""Knowledge cache: verified facts per (system, commit), picked by keyword overlap with the idea."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mscenario.models import KnowledgeFact, utcnow
from mscenario.verify import cite_key

WORD_RE = re.compile(r"[a-z0-9_]{3,}")
STOP = frozenset(
    "the and for with that this from into how why what does not are can its you your when then than "
    "about over under use using used one two let get got run runs make makes show shows video".split()
)


def tokenize(*parts: str) -> set[str]:
    words: set[str] = set()
    for part in parts:
        words |= {w for w in WORD_RE.findall(part.lower()) if w not in STOP}
    return words


def idea_terms(idea: Mapping[str, Any]) -> set[str]:
    texts = [
        str(idea.get("title") or ""), str(idea.get("description") or ""), str(idea.get("key_takeaway") or ""),
        " ".join(idea.get("tags") or []), " ".join(idea.get("demo_commands") or []),
        " ".join(idea.get("must_show") or []),
    ]  # fmt: skip
    return tokenize(*texts)


def fact_tags(text: str, cite: Mapping[str, Any]) -> list[str]:
    where = str(cite.get("file") or cite.get("url") or "")
    return sorted(tokenize(text, where, str(cite["quote"])))


class KnowledgeCache:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def relevant(
        self, system: str, commit: str, terms: set[str], *, limit: int = 15, max_chars: int = 3000, min_score: int = 2
    ) -> list[KnowledgeFact]:
        """Best facts first; a fact needs at least `min_score` shared terms so noise stays out of the prompt."""
        rows = (
            await self.s.execute(
                select(KnowledgeFact).where(KnowledgeFact.system == system, KnowledgeFact.commit == commit)
            )
        ).scalars()
        scored = []
        for row in rows:
            score = len(terms & set(row.tags))
            if score >= min_score:
                scored.append((score, row.uses, -row.id, row))
        scored.sort(key=lambda t: t[:3], reverse=True)
        picked: list[KnowledgeFact] = []
        used = 0
        for _, _, _, row in scored:
            cost = len(row.text) + len(str(row.cite.get("quote", ""))) + 40
            if len(picked) >= limit or used + cost > max_chars:
                break
            picked.append(row)
            used += cost
        return picked

    async def store(self, system: str, commit: str, facts: Sequence[Mapping[str, Any]]) -> int:
        """Add verified facts; a fact with an already known citation is skipped. Returns how many were new."""
        added = 0
        for fact in facts:
            key = cite_key(fact["cite"])
            exists = (
                await self.s.execute(
                    select(KnowledgeFact.id).where(
                        KnowledgeFact.system == system, KnowledgeFact.commit == commit, KnowledgeFact.key == key
                    )
                )
            ).first()
            if exists:
                continue
            cite = dict(fact["cite"])
            self.s.add(
                KnowledgeFact(
                    system=system,
                    commit=commit,
                    key=key,
                    text=str(fact["text"]),
                    cite=cite,
                    kind="code" if "file" in cite else "url",
                    tags=fact_tags(str(fact["text"]), cite),
                )  # fmt: skip
            )
            added += 1
        await self.s.flush()
        return added

    async def touch(self, rows: Sequence[KnowledgeFact]) -> None:
        now = utcnow()
        for row in rows:
            row.uses += 1
            row.last_used_at = now
        await self.s.flush()

    async def count(self, system: str, commit: str | None = None) -> int:
        q = select(KnowledgeFact.id).where(KnowledgeFact.system == system)
        if commit:
            q = q.where(KnowledgeFact.commit == commit)
        return len((await self.s.execute(q)).all())
