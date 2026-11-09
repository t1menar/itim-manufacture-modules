"""Runtime prompts in the database: immutable versions, activation with a revision, audit (D16 / C40)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mvideo.agents.prompts import SEMVER, digest, placeholders_of, semver_key
from mvideo.db.models import PromptActive, PromptAudit, PromptVersion


class PromptConflict(Exception):
    """The version exists, or the activation `If-Match` revision is stale."""


class PromptInvalid(ValueError):
    pass


async def get_version(session: AsyncSession, step: str, version: str) -> PromptVersion | None:
    stmt = select(PromptVersion).where(PromptVersion.step == step, PromptVersion.version == version)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_versions(session: AsyncSession) -> list[PromptVersion]:
    return list((await session.execute(select(PromptVersion))).scalars())


async def get_active(session: AsyncSession, step: str) -> PromptActive | None:
    return await session.get(PromptActive, step)


async def list_active(session: AsyncSession) -> list[PromptActive]:
    return list((await session.execute(select(PromptActive))).scalars())


async def audit(session: AsyncSession, **fields: Any) -> None:
    session.add(PromptAudit(**fields))


async def list_audit(session: AsyncSession, limit: int = 100) -> list[PromptAudit]:
    stmt = select(PromptAudit).order_by(PromptAudit.at.desc(), PromptAudit.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def create_version(
    session: AsyncSession,
    step: str,
    version: str,
    *,
    claude_md: str,
    task_md: str = "",
    meta: dict[str, Any] | None = None,
    note: str | None = None,
    actor: str | None = None,
    action: str = "create",
) -> PromptVersion:
    """Add an immutable version; task placeholders must be ones the step supplies."""
    if not SEMVER.match(version):
        raise PromptInvalid(f"version {version!r} is not MAJOR.MINOR.PATCH")
    if not claude_md.strip():
        raise PromptInvalid("claude_md is empty")
    if step != "skill" and not task_md.strip():
        raise PromptInvalid("task_md is empty")
    if await get_version(session, step, version) is not None:
        raise PromptConflict(f"{step}@{version} exists; versions are immutable, create a new one")
    names = placeholders_of(task_md)
    known = {n for v in await _versions_of(session, step) for n in v.placeholders}
    unknown = sorted(set(names) - known) if known else []
    if unknown:
        raise PromptInvalid(f"unknown placeholders {unknown}; the step supplies {sorted(known)}")
    row = PromptVersion(
        step=step, version=version, claude_md=claude_md, task_md=task_md, placeholders=names,
        meta=meta or {}, sha256=digest(claude_md, task_md), note=note, created_by=actor,
    )  # fmt: skip
    session.add(row)
    await audit(session, actor=actor, action=action, step=step, version=version, note=note)
    await session.flush()
    return row


async def _versions_of(session: AsyncSession, step: str) -> list[PromptVersion]:
    stmt = select(PromptVersion).where(PromptVersion.step == step)
    return list((await session.execute(stmt)).scalars())


async def activate(
    session: AsyncSession, step: str, version: str, *, expected_revision: int | None, actor: str | None = None
) -> PromptActive:
    """Make `version` active. `expected_revision` is the `If-Match` value (0: nothing active yet)."""
    if await get_version(session, step, version) is None:
        raise PromptInvalid(f"{step}@{version} does not exist")
    current = await session.get(PromptActive, step, with_for_update=True)
    have = current.revision if current else 0
    if expected_revision is not None and expected_revision != have:
        raise PromptConflict(f"active revision of {step} is {have}, not {expected_revision}")
    previous = current.version if current else None
    if current is None:
        current = PromptActive(step=step, version=version, revision=1, updated_by=actor)
        session.add(current)
    else:
        current.version, current.revision, current.updated_by = version, current.revision + 1, actor
    await audit(
        session, actor=actor, action="activate", step=step, version=version, previous_version=previous
    )
    await session.flush()
    return current


def read_packaged(root: Path) -> dict[str, list[tuple[str, str, str, dict[str, Any]]]]:
    """`{step: [(version, claude_md, task_md, meta)]}` oldest first, read from `prompts/`."""
    out: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = {}
    for step_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        step = step_dir.name
        for vdir in sorted(
            (p for p in step_dir.iterdir() if p.is_dir() and SEMVER.match(p.name)),
            key=lambda p: semver_key(p.name),
        ):
            if step == "skill":
                out.setdefault(step, []).append((vdir.name, (vdir / "SKILL.md").read_text("utf-8"), "", {}))
            else:
                meta = json.loads((vdir / "meta.json").read_text("utf-8"))
                out.setdefault(step, []).append(
                    (
                        vdir.name,
                        (vdir / "CLAUDE.md").read_text("utf-8"),
                        (vdir / "task.md").read_text("utf-8"),
                        meta,
                    )
                )
    return out


async def seed_from_files(session: AsyncSession, root: Path) -> list[str]:
    """Insert packaged versions the database lacks; activate the newest of a step with none active.

    Existing rows are never changed, so an edited version keeps its text. Returns the ids added.
    """
    added: list[str] = []
    for step, versions in (await asyncio.to_thread(read_packaged, root)).items():
        for version, claude, task, meta in versions:
            if await get_version(session, step, version) is not None:
                continue
            session.add(PromptVersion(
                step=step, version=version, claude_md=claude, task_md=task,
                placeholders=list(meta.get("placeholders", [])), meta=meta, sha256=digest(claude, task),
                created_by="seed",
            ))  # fmt: skip
            await audit(session, actor="seed", action="seed", step=step, version=version)
            added.append(f"{step}@{version}")
        if versions and await get_active(session, step) is None:
            session.add(PromptActive(step=step, version=versions[-1][0], revision=1, updated_by="seed"))
    await session.flush()
    return added
