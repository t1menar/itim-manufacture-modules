"""`/admin/v1/prompts`: runtime prompts as immutable versions, activation, audit (04 3.4, D16)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationError

from mvideo.agents.prompts import semver_key
from mvideo.api.problems import ProblemError
from mvideo.auth import require_bearer
from mvideo.db import prompts_repo
from mvideo.db.engine import session_factory

router = APIRouter(prefix="/admin/v1/prompts", dependencies=[Depends(require_bearer)])


class NewVersion(BaseModel):
    version: str
    claude_md: str
    task_md: str = ""
    note: str | None = Field(default=None, max_length=500)


class Activate(BaseModel):
    version: str


def _factory(request: Request) -> Any:
    engine = request.app.state.engine
    if engine is None:
        raise ProblemError(503, "not_ready", "No database is configured")
    return session_factory(engine)


def _actor(request: Request) -> str:
    return request.headers.get("x-actor", "admin")[:100]


async def _body[T: BaseModel](request: Request, model: type[T]) -> T:
    try:
        return model.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        raise ProblemError(422, "input_invalid", f"Request body is invalid: {exc}") from exc


def _view(row: Any, with_text: bool = False) -> dict[str, Any]:
    out = {
        "step": row.step, "version": row.version, "sha256": row.sha256, "placeholders": row.placeholders,
        "note": row.note, "created_by": row.created_by, "created_at": row.created_at.isoformat(),
    }  # fmt: skip
    if with_text:
        out |= {"claude_md": row.claude_md, "task_md": row.task_md, "meta": row.meta}
    return out


@router.get("")
async def list_prompts(request: Request) -> list[dict[str, Any]]:
    async with _factory(request)() as s:
        versions = await prompts_repo.list_versions(s)
        active = {a.step: a for a in await prompts_repo.list_active(s)}
    steps: dict[str, list[Any]] = {}
    for v in versions:
        steps.setdefault(v.step, []).append(v)
    return [
        {
            "step": step,
            "versions": [v.version for v in sorted(rows, key=lambda r: semver_key(r.version))],
            "default": active[step].version if step in active else None,
            "revision": active[step].revision if step in active else 0,
            "sha256": {v.version: v.sha256 for v in rows},
        }
        for step, rows in sorted(steps.items())
    ]


@router.get("/audit")
async def audit_log(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    async with _factory(request)() as s:
        rows = await prompts_repo.list_audit(s, max(1, min(limit, 500)))
    return [
        {"at": r.at.isoformat(), "actor": r.actor, "action": r.action, "step": r.step, "version": r.version,
         "previous_version": r.previous_version, "note": r.note}
        for r in rows
    ]  # fmt: skip


@router.get("/{step}/{version}")
async def get_prompt(step: str, version: str, request: Request) -> dict[str, Any]:
    async with _factory(request)() as s:
        row = await prompts_repo.get_version(s, step, version)
    if row is None:
        raise ProblemError(404, "not_found", f"No prompt {step}@{version}")
    return _view(row, with_text=True)


@router.post("/{step}", status_code=201)
async def create_prompt(step: str, request: Request) -> dict[str, Any]:
    body = await _body(request, NewVersion)
    try:
        async with _factory(request)() as s, s.begin():
            row = await prompts_repo.create_version(
                s, step, body.version, claude_md=body.claude_md, task_md=body.task_md, note=body.note,
                actor=_actor(request),
            )  # fmt: skip
            return _view(row, with_text=True)
    except prompts_repo.PromptConflict as exc:
        raise ProblemError(409, "conflict", str(exc)) from exc
    except prompts_repo.PromptInvalid as exc:
        raise ProblemError(422, "input_invalid", str(exc)) from exc


@router.put("/{step}/active")
async def activate_prompt(step: str, request: Request) -> dict[str, Any]:
    """`If-Match: <revision>` is required: the revision from the listing (0 when nothing is active yet)."""
    header = request.headers.get("if-match")
    if header is None:
        raise ProblemError(428, "precondition_required", "If-Match with the current revision is required")
    try:
        revision = int(header.strip('"'))
    except ValueError as exc:
        raise ProblemError(400, "bad_request", "If-Match must be the integer revision") from exc
    body = await _body(request, Activate)
    try:
        async with _factory(request)() as s, s.begin():
            row = await prompts_repo.activate(
                s, step, body.version, expected_revision=revision, actor=_actor(request)
            )
            return {"step": step, "version": row.version, "revision": row.revision}
    except prompts_repo.PromptConflict as exc:
        raise ProblemError(412, "precondition_failed", str(exc)) from exc
    except prompts_repo.PromptInvalid as exc:
        raise ProblemError(404, "not_found", str(exc)) from exc
