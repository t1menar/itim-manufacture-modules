"""Domain logic: backlog, playlists, scheduling, run events and outcome statistics.

Everything here is transport-agnostic. The HTTP API and the future platform adapter (source and
`run.finished` subscriber) are thin callers of `IdeaService`.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from midea import schemas
from midea.models import (
    Environment,
    Idea,
    IdeaOutcome,
    IdeaRevision,
    IdeaRun,
    IdeaStatusLog,
    Playlist,
    PlaylistIdea,
    Rubric,
    utcnow,
)
from midea.status import IN_FLIGHT, IdeaStatus, TransitionError, check_transition

CONTENT_FIELDS = (
    "title", "description", "key_takeaway", "hook", "audience", "language", "rubric_code",
    "environment_id", "depth", "difficulty", "tags", "demo_commands", "expected_result", "must_show",
    "must_avoid", "source_refs", "references", "constraints", "target_duration_s", "notes",
    "scenario_brief", "video_brief", "design_notes", "palette", "instructions",
)  # fmt: skip
RUN_TERMINAL = {"succeeded", "failed", "cancelled"}


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class NotReady(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("idea is not ready for production: " + "; ".join(issues))
        self.issues = issues


@dataclass(frozen=True, slots=True)
class SchedulerPolicy:
    max_in_flight: int = 3
    min_interval_s: int = 0
    paused: bool = False


def _per_1000(n: int, views: int) -> float:
    return round(n * 1000 / views, 3) if views else 0.0


def idea_ref(idea: Idea) -> str:
    return f"idea:{idea.id}:v{idea.rev}"


def readiness_issues(idea: Idea) -> list[str]:
    """What the pipeline needs before an idea may be queued (cheap to check here, expensive to find late)."""
    issues = []
    if not idea.key_takeaway:
        issues.append("key_takeaway is required: one sentence the viewer must remember")
    if not idea.rubric_code:
        issues.append("rubric_code is required")
    if idea.environment_id is None:
        issues.append("environment is required")
    if len(idea.description.split()) < 8:
        issues.append("description is too short to plan a video (at least 8 words)")
    return issues


class IdeaService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # -- reference data ------------------------------------------------------------------------
    async def upsert_environment(self, data: schemas.EnvironmentIn) -> Environment:
        env = (await self.s.execute(select(Environment).where(Environment.code == data.code))).scalar_one_or_none()
        if env is None:
            env = Environment(**data.model_dump())
            self.s.add(env)
        else:
            for k, v in data.model_dump().items():
                setattr(env, k, v)
        await self.s.flush()
        return env

    async def upsert_rubric(self, data: schemas.RubricIn) -> Rubric:
        rub = await self.s.get(Rubric, data.code)
        if rub is None:
            rub = Rubric(**data.model_dump())
            self.s.add(rub)
        else:
            for k, v in data.model_dump().items():
                setattr(rub, k, v)
        await self.s.flush()
        return rub

    async def environment_by_code(self, code: str) -> Environment:
        env = (await self.s.execute(select(Environment).where(Environment.code == code))).scalar_one_or_none()
        if env is None:
            raise NotFound(f"environment {code!r}")
        return env

    async def _check_rubric(self, code: str | None) -> None:
        if code is not None and await self.s.get(Rubric, code) is None:
            raise NotFound(f"rubric {code!r}")

    # -- playlists -----------------------------------------------------------------------------
    async def create_playlist(self, data: schemas.PlaylistIn) -> Playlist:
        if (await self.s.execute(select(Playlist.id).where(Playlist.code == data.code))).first():
            raise Conflict(f"playlist {data.code!r} already exists")
        env_id = (await self.environment_by_code(data.environment_code)).id if data.environment_code else None
        pl = Playlist(**data.model_dump(exclude={"environment_code"}), environment_id=env_id)
        self.s.add(pl)
        await self.s.flush()
        return pl

    async def playlist_by_code(self, code: str) -> Playlist:
        pl = (await self.s.execute(select(Playlist).where(Playlist.code == code))).scalar_one_or_none()
        if pl is None:
            raise NotFound(f"playlist {code!r}")
        return pl

    async def update_playlist(self, code: str, patch: schemas.PlaylistPatch) -> Playlist:
        pl = await self.playlist_by_code(code)
        changes = patch.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(pl, k, v)
        if changes:
            pl.rev += 1
        await self.s.flush()
        return pl

    async def list_playlists(self, status: str | None = None) -> Sequence[Playlist]:
        q = select(Playlist).order_by(Playlist.sort_order, Playlist.id)
        if status:
            q = q.where(Playlist.status == status)
        return (await self.s.execute(q)).scalars().all()

    async def playlist_idea_ids(self, playlist_id: int) -> list[int]:
        q = (
            select(PlaylistIdea.idea_id)
            .where(PlaylistIdea.playlist_id == playlist_id)
            .order_by(PlaylistIdea.position, PlaylistIdea.idea_id)
        )
        return list((await self.s.execute(q)).scalars().all())

    async def add_to_playlist(self, code: str, idea_id: int, position: int | None = None) -> None:
        pl = await self.playlist_by_code(code)
        await self.get_idea(idea_id)
        existing = await self.s.get(PlaylistIdea, (pl.id, idea_id))
        if existing is not None:
            if position is not None:
                existing.position = position
            return
        if position is None:
            last = (
                await self.s.execute(select(func.max(PlaylistIdea.position)).where(PlaylistIdea.playlist_id == pl.id))
            ).scalar()
            position = 0 if last is None else last + 1
        self.s.add(PlaylistIdea(playlist_id=pl.id, idea_id=idea_id, position=position))
        await self.s.flush()

    async def remove_from_playlist(self, code: str, idea_id: int) -> None:
        pl = await self.playlist_by_code(code)
        await self.s.execute(
            delete(PlaylistIdea).where(PlaylistIdea.playlist_id == pl.id, PlaylistIdea.idea_id == idea_id)
        )

    async def reorder_playlist(self, code: str, idea_ids: list[int]) -> None:
        pl = await self.playlist_by_code(code)
        current = await self.playlist_idea_ids(pl.id)
        if sorted(current) != sorted(idea_ids):
            raise Conflict("idea_ids must list exactly the ideas of the playlist")
        for pos, iid in enumerate(idea_ids):
            row = await self.s.get(PlaylistIdea, (pl.id, iid))
            assert row is not None
            row.position = pos
        await self.s.flush()

    # -- ideas ---------------------------------------------------------------------------------
    async def get_idea(self, idea_id: int) -> Idea:
        idea = await self.s.get(Idea, idea_id)
        if idea is None:
            raise NotFound(f"idea {idea_id}")
        return idea

    async def create_idea(self, data: schemas.IdeaIn) -> Idea:
        await self._check_rubric(data.rubric_code)
        env_id = (await self.environment_by_code(data.environment_code)).id if data.environment_code else None
        fields = data.model_dump(exclude={"environment_code", "playlist_codes"})
        idea = Idea(**fields, environment_id=env_id, status=IdeaStatus.DRAFT.value)
        self.s.add(idea)
        await self.s.flush()
        for code in data.playlist_codes:
            await self.add_to_playlist(code, idea.id)
        await self._snapshot(idea)  # playlists as of the revision; later membership changes do not bump it
        self.s.add(IdeaStatusLog(idea_id=idea.id, src="", dst=idea.status, note="created"))
        return idea

    async def update_idea(self, idea_id: int, patch: schemas.IdeaPatch) -> Idea:
        idea = await self.get_idea(idea_id)
        changes = patch.model_dump(exclude_unset=True)
        env_code = changes.pop("environment_code", None)
        if "environment_code" in patch.model_fields_set:
            idea.environment_id = (await self.environment_by_code(env_code)).id if env_code else None
        if "rubric_code" in changes:
            await self._check_rubric(changes["rubric_code"])
        if idea.status in IN_FLIGHT:
            raise Conflict("the idea is in production; wait for the run or cancel it before editing")
        content_changed = "environment_code" in patch.model_fields_set
        for k, v in changes.items():
            if getattr(idea, k) != v:
                setattr(idea, k, v)
                content_changed = content_changed or k in CONTENT_FIELDS
        if content_changed:
            idea.rev += 1
            await self.s.flush()
            await self._snapshot(idea)
        await self.s.flush()
        return idea

    async def list_ideas(
        self,
        *,
        status: str | None = None,
        playlist_code: str | None = None,
        rubric_code: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Idea]:
        q = select(Idea).order_by(Idea.priority.desc(), Idea.id)
        if status:
            q = q.where(Idea.status == status)
        if rubric_code:
            q = q.where(Idea.rubric_code == rubric_code)
        if playlist_code:
            pl = await self.playlist_by_code(playlist_code)
            q = q.join(PlaylistIdea, PlaylistIdea.idea_id == Idea.id).where(PlaylistIdea.playlist_id == pl.id)
        return (await self.s.execute(q.limit(limit).offset(offset))).scalars().all()

    async def set_status(
        self, idea_id: int, dst: IdeaStatus, *, note: str | None = None, run_id: str | None = None
    ) -> Idea:
        idea = await self.get_idea(idea_id)
        src = IdeaStatus(idea.status)
        if src == dst:
            return idea
        check_transition(src, dst)
        if dst is IdeaStatus.QUEUED and src in (IdeaStatus.DRAFT, IdeaStatus.FAILED, IdeaStatus.ARCHIVED):
            issues = readiness_issues(idea)
            if issues:
                raise NotReady(issues)
        idea.status = dst.value
        if dst is IdeaStatus.QUEUED:
            idea.last_error = None
        self.s.add(IdeaStatusLog(idea_id=idea.id, src=src.value, dst=dst.value, run_id=run_id, note=note))
        await self.s.flush()
        return idea

    async def delete_idea(self, idea_id: int) -> None:
        idea = await self.get_idea(idea_id)
        if idea.status in IN_FLIGHT:
            raise Conflict("the idea is in production")
        await self.s.delete(idea)

    # -- document handed to the pipeline -------------------------------------------------------
    async def build_document(self, idea: Idea) -> dict[str, Any]:
        env = await self.s.get(Environment, idea.environment_id) if idea.environment_id else None
        rub = await self.s.get(Rubric, idea.rubric_code) if idea.rubric_code else None
        pls = (
            (
                await self.s.execute(
                    select(Playlist.code)
                    .join(PlaylistIdea, PlaylistIdea.playlist_id == Playlist.id)
                    .where(PlaylistIdea.idea_id == idea.id)
                    .order_by(Playlist.sort_order)
                )
            )
            .scalars()
            .all()
        )
        doc: dict[str, Any] = {
            "id": idea.id, "rev": idea.rev, "idea_ref": idea_ref(idea),
            "title": idea.title, "description": idea.description, "key_takeaway": idea.key_takeaway,
            "hook": idea.hook, "audience": idea.audience, "language": idea.language,
            "rubric": {"code": rub.code, "title": rub.title, "template": rub.template} if rub else None,
            "environment": (
                {
                    "code": env.code, "sandbox_image": env.sandbox_image,
                    "version_expect": env.version_expect, "allowed_repos": env.allowed_repos,
                }
                if env else None
            ),
            "playlists": list(pls), "depth": idea.depth, "difficulty": idea.difficulty,
            "tags": idea.tags, "demo_commands": idea.demo_commands,
            "expected_result": idea.expected_result, "must_show": idea.must_show,
            "must_avoid": idea.must_avoid, "source_refs": idea.source_refs,
            "references": idea.references, "constraints": idea.constraints,
            "target_duration_s": idea.target_duration_s, "priority": idea.priority,
            "notes": idea.notes, "author": idea.author, "scenario_brief": idea.scenario_brief,
            "video_brief": idea.video_brief, "design_notes": idea.design_notes, "palette": idea.palette,
            "instructions": idea.instructions,
        }  # fmt: skip
        return doc

    async def _snapshot(self, idea: Idea) -> None:
        self.s.add(IdeaRevision(idea_id=idea.id, rev=idea.rev, document=await self.build_document(idea)))

    async def revision_document(self, idea_id: int, rev: int) -> dict[str, Any]:
        row = await self.s.get(IdeaRevision, (idea_id, rev))
        if row is None:
            raise NotFound(f"idea {idea_id} revision {rev}")
        return row.document

    # -- scheduling ----------------------------------------------------------------------------
    async def in_flight_count(self) -> int:
        q = select(func.count()).select_from(Idea).where(Idea.status.in_([s.value for s in IN_FLIGHT]))
        return int((await self.s.execute(q)).scalar_one())

    async def pick_next(self, policy: SchedulerPolicy, now: dt.datetime | None = None, limit: int = 1) -> list[Idea]:
        """Queued ideas to start now: respects the in-flight cap, the interval, playlists and environments."""
        now = now or utcnow()
        if policy.paused:
            return []
        slots = policy.max_in_flight - await self.in_flight_count()
        if slots <= 0:
            return []
        if policy.min_interval_s > 0:
            last = (await self.s.execute(select(func.max(Idea.dispatched_at)))).scalar()
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=dt.UTC)
                if (now - last).total_seconds() < policy.min_interval_s:
                    return []
        queued = (await self.s.execute(select(Idea).where(Idea.status == IdeaStatus.QUEUED.value))).scalars().all()
        if not queued:
            return []
        active_envs = set((await self.s.execute(select(Environment.id).where(Environment.active))).scalars().all())
        rank = await self._playlist_rank([i.id for i in queued])
        eligible = []
        for idea in queued:
            if idea.environment_id is not None and idea.environment_id not in active_envs:
                continue
            if idea.id in rank and rank[idea.id] is None:
                continue  # only in inactive playlists
            eligible.append(idea)
        eligible.sort(key=lambda i: (-i.priority, rank.get(i.id) or (0, 0), i.id))
        return eligible[: min(limit, slots)]

    async def _playlist_rank(self, idea_ids: list[int]) -> dict[int, tuple[int, int] | None]:
        """idea -> best (playlist sort_order, position) among active playlists; None = only inactive ones."""
        rows = (
            await self.s.execute(
                select(PlaylistIdea.idea_id, Playlist.status, Playlist.sort_order, PlaylistIdea.position)
                .join(Playlist, Playlist.id == PlaylistIdea.playlist_id)
                .where(PlaylistIdea.idea_id.in_(idea_ids))
            )
        ).all()
        best: dict[int, tuple[int, int] | None] = {}
        for idea_id, status, order, pos in rows:
            cur = best.get(idea_id, None)
            if status != "active":
                best.setdefault(idea_id, None)
                continue
            cand = (order, pos)
            best[idea_id] = cand if cur is None or cand < cur else cur
        return best

    async def dispatch(self, idea_id: int, run_id: str, now: dt.datetime | None = None) -> Idea:
        """The platform accepted `idea.ready`: the idea is bound to a run."""
        existing = await self.s.get(IdeaRun, run_id)
        if existing is not None:
            return await self.get_idea(existing.idea_id)  # idempotent
        idea = await self.set_status(idea_id, IdeaStatus.DISPATCHED, run_id=run_id)
        idea.run_id = run_id
        idea.dispatched_at = now or utcnow()
        self.s.add(IdeaRun(run_id=run_id, idea_id=idea.id, idea_rev=idea.rev))
        await self.s.flush()
        return idea

    # -- run events from the platform ----------------------------------------------------------
    async def apply_run_event(self, ev: schemas.RunEvent) -> Idea | None:
        """Idempotent and monotonic: a replayed or reordered event never moves an idea backwards."""
        run = await self.s.get(IdeaRun, ev.run_id)
        if run is None:
            return None  # a run this module did not start
        idea = await self.get_idea(run.idea_id)
        now = ev.occurred_at or utcnow()
        if run.status in RUN_TERMINAL:
            return idea
        if ev.cost_usd is not None:
            run.cost_usd = max(run.cost_usd, Decimal(ev.cost_usd))
        if ev.status == "running":
            run.status = "running"
            run.started_at = run.started_at or now
            if IdeaStatus(idea.status) is IdeaStatus.DISPATCHED and idea.run_id == run.run_id:
                await self.set_status(idea.id, IdeaStatus.IN_PRODUCTION, run_id=run.run_id)
        else:
            run.status = ev.status
            run.finished_at = now
            run.error = ev.error
            if idea.run_id == run.run_id and IdeaStatus(idea.status) in IN_FLIGHT:
                dst = IdeaStatus.DONE if ev.status == "succeeded" else IdeaStatus.FAILED
                idea.last_error = ev.error if dst is IdeaStatus.FAILED else None
                await self.set_status(idea.id, dst, run_id=run.run_id, note=ev.error)
        await self.s.flush()
        await self._refresh_cost(idea)
        return idea

    async def _refresh_cost(self, idea: Idea) -> None:
        total = (
            await self.s.execute(select(func.coalesce(func.sum(IdeaRun.cost_usd), 0)).where(IdeaRun.idea_id == idea.id))
        ).scalar_one()
        idea.cost_spent_usd = Decimal(total)

    async def release_stale(self, older_than: dt.timedelta, now: dt.datetime | None = None) -> list[int]:
        """Return ideas stuck in `dispatched` (the platform never started them) to the queue."""
        now = now or utcnow()
        rows = (await self.s.execute(select(Idea).where(Idea.status == IdeaStatus.DISPATCHED.value))).scalars().all()
        released = []
        for idea in rows:
            at = idea.dispatched_at
            if at is not None and at.tzinfo is None:
                at = at.replace(tzinfo=dt.UTC)
            if at is not None and now - at > older_than:
                await self.set_status(idea.id, IdeaStatus.QUEUED, note="stale dispatch released")
                run = await self.s.get(IdeaRun, idea.run_id) if idea.run_id else None
                if run is not None and run.status not in RUN_TERMINAL:
                    run.status = "cancelled"
                    run.finished_at = now
                released.append(idea.id)
        return released

    # -- outcomes and statistics ---------------------------------------------------------------
    async def add_outcome(self, idea_id: int, data: schemas.OutcomeIn) -> IdeaOutcome:
        idea = await self.get_idea(idea_id)
        if IdeaStatus(idea.status) is not IdeaStatus.DONE:
            raise Conflict("outcomes can be recorded only for published (done) ideas")
        out = IdeaOutcome(idea_id=idea_id, **data.model_dump(exclude={"measured_at"}))
        if data.measured_at:
            out.measured_at = data.measured_at
        self.s.add(out)
        await self.s.flush()
        return out

    async def stats(self, group_by: str) -> list[schemas.GroupStat]:
        """Saves, shares and follows per 1000 views, from the latest measurement of each published idea."""
        if group_by not in {"rubric", "depth", "playlist", "environment"}:
            raise ValueError("group_by must be rubric, depth, playlist or environment")
        outcomes = (await self.s.execute(select(IdeaOutcome).order_by(IdeaOutcome.measured_at))).scalars().all()
        latest: dict[tuple[int, str], IdeaOutcome] = {}
        for o in outcomes:
            latest[(o.idea_id, o.platform)] = o
        ideas = {
            i.id: i for i in (await self.s.execute(select(Idea).where(Idea.id.in_({k[0] for k in latest})))).scalars()
        }
        keys = await self._group_keys(group_by, list(ideas.values()))
        agg: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"ideas": set(), "views": 0, "saves": 0, "shares": 0, "follows": 0, "cost": Decimal(0)}
        )
        for (idea_id, _), o in latest.items():
            for key in keys.get(idea_id, ["-"]):
                a = agg[key]
                a["ideas"].add(idea_id)
                a["views"] += o.views
                a["saves"] += o.saves
                a["shares"] += o.shares
                a["follows"] += o.follows
        for a in agg.values():
            a["cost"] = sum((ideas[i].cost_spent_usd for i in a["ideas"]), Decimal(0))
        out = []
        for key, a in sorted(agg.items()):
            views = int(a["views"])
            out.append(
                schemas.GroupStat(
                    key=key, ideas=len(a["ideas"]), views=views,
                    saves_per_1000=_per_1000(a["saves"], views),
                    shares_per_1000=_per_1000(a["shares"], views),
                    follows_per_1000=_per_1000(a["follows"], views), cost_usd=a["cost"],
                )
            )  # fmt: skip
        return out

    async def _group_keys(self, group_by: str, ideas: list[Idea]) -> dict[int, list[str]]:
        if group_by == "rubric":
            return {i.id: [i.rubric_code or "-"] for i in ideas}
        if group_by == "depth":
            return {i.id: [i.depth] for i in ideas}
        if group_by == "environment":
            envs = {e.id: e.code for e in (await self.s.execute(select(Environment))).scalars()}
            return {i.id: [envs.get(i.environment_id or -1, "-")] for i in ideas}
        rows = (
            await self.s.execute(
                select(PlaylistIdea.idea_id, Playlist.code)
                .join(Playlist, Playlist.id == PlaylistIdea.playlist_id)
                .where(PlaylistIdea.idea_id.in_([i.id for i in ideas]))
            )
        ).all()
        keys: dict[int, list[str]] = defaultdict(list)
        for idea_id, code in rows:
            keys[idea_id].append(code)
        return dict(keys)


__all__ = [
    "Conflict",
    "IdeaService",
    "NotFound",
    "NotReady",
    "SchedulerPolicy",
    "TransitionError",
    "idea_ref",
]
