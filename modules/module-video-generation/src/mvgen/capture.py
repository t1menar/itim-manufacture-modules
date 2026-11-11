"""Capture: a planner agent proposes `capture.plan.json`, a deterministic runner records the real output.

The agent never produces numbers shown on screen; `CaptureRunner` executes the plan in a sandbox and
`check_values` verifies what came back. A failed run costs one planner retry with the exact problems and
the execution log. A recorded capture is cached by the hash of (plan, commands, image) so revisions that
do not touch the commands reuse it without sandbox and without agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mvgen.agent import BudgetExceeded, Usage
from mvgen.db import transaction
from mvgen.models import CaptureCache

NUMBER = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


class CaptureFailure(Exception):
    """`code`: version_mismatch (not retryable) | not_reproducible | timeout."""

    def __init__(self, code: str, message: str, log: str = "") -> None:
        super().__init__(message)
        self.code, self.log = code, log


class CaptureBlocked(Exception):
    def __init__(self, code: str, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.code, self.problems = code, problems or []


@dataclass(frozen=True, slots=True)
class PlanRequest:
    script: dict[str, Any]
    research: dict[str, Any]
    brief: dict[str, Any]  # design_brief(idea): only idea-level wishes
    image: dict[str, Any]  # sandbox image description: key, version_expect, sessions
    attempt: int = 0
    problems: list[str] = field(default_factory=list)
    execution_log: str = ""
    session_id: str | None = None  # resume the same agent context on a fix round
    max_budget_usd: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True)
class PlanResponse:
    plan: dict[str, Any]
    usage: Usage = field(default_factory=Usage)
    session_id: str | None = None


class CapturePlanner(Protocol):
    async def plan(self, request: PlanRequest) -> PlanResponse: ...


class CaptureRunner(Protocol):
    async def run(self, plan: dict[str, Any], script: dict[str, Any], run_id: str) -> tuple[dict[str, Any], str]:
        """Execute the plan; returns (capture.json document, log). Raises CaptureFailure."""
        ...


def script_commands(script: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for scene in script.get("scenes", []):
        term = scene.get("terminal") or {}
        for ev in term.get("events", []):
            if "cmd" in ev:
                out[ev["cmd"]] = ev.get("text", "")
    return out


def plan_issues(plan: dict[str, Any], script: dict[str, Any]) -> list[str]:
    """Cheap structural checks before a sandbox is started."""
    problems: list[str] = []
    sessions = plan.get("sessions")
    ops = plan.get("ops")
    if not isinstance(sessions, dict) or not sessions:
        return ["plan.sessions must be a non-empty object"]
    if not isinstance(ops, list) or not ops:
        return ["plan.ops must be a non-empty list"]
    cmds = script_commands(script)
    ran: set[str] = set()
    for i, op in enumerate(ops):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind not in {"open", "close", "sleep", "setup", "run", "value"}:
            problems.append(f"ops[{i}]: unknown op {kind!r}")
            continue
        if kind in {"open", "close", "setup", "value"} and op.get("session") not in sessions:
            problems.append(f"ops[{i}]: session {op.get('session')!r} is not declared")
        if kind == "run":
            if op.get("cmd") not in cmds:
                problems.append(f"ops[{i}]: command {op.get('cmd')!r} is not in the script")
            else:
                ran.add(op["cmd"])
        if kind == "value" and not op.get("why_equal"):
            problems.append(f"ops[{i}]: value {op.get('name')!r} needs why_equal")
    problems += [f"script command {c!r} is never run by the plan" for c in cmds if c not in ran]
    needed = set(script.get("captures") or {})
    named = {op.get("name") for op in ops if isinstance(op, dict) and op.get("op") == "value"}
    problems += [f"script capture {n!r} has no value op" for n in sorted(needed - named)]
    return problems


def check_values(capture: dict[str, Any]) -> list[str]:
    problems = []
    for name, v in capture.get("values", {}).items():
        if v["value"] == "":
            problems.append(f"value {name}: empty (raw {v.get('raw')!r})")
        elif v.get("kind", "number") == "number" and not NUMBER.match(v["value"]):
            problems.append(f"value {name}: {v['value']!r} is not a number")
    return problems


def capture_key(plan: dict[str, Any], script: dict[str, Any], image_key: str) -> str:
    body = json.dumps(
        {
            "plan": plan,
            "commands": script_commands(script),
            "captures": script.get("captures") or {},
            "image": image_key,
        },
        sort_keys=True,
    )
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(slots=True)
class CaptureOutcome:
    plan: dict[str, Any]
    capture: dict[str, Any]
    log: str
    usage: Usage
    rounds: int
    cached: bool = False


class CaptureService:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        planner: CapturePlanner,
        runner: CaptureRunner,
        *,
        fix_rounds: int = 2,
        describe: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.sm, self.planner, self.runner, self.fix_rounds = sm, planner, runner, fix_rounds
        self.describe = describe  # image key -> what the planner is told (sessions, expected version)

    async def run(
        self,
        script: dict[str, Any],
        research: dict[str, Any],
        brief: dict[str, Any],
        image: dict[str, Any],
        run_id: str,
        budget_usd: Decimal,
        previous: tuple[dict[str, Any], dict[str, Any]] | None = None,
    ) -> CaptureOutcome:
        """`previous` = (plan, capture) of an earlier visit: reused as is when the script commands did not change."""
        if previous is not None:
            plan, capture = previous
            if capture_key(plan, script, image["key"]) == capture.get("cache_key"):
                return CaptureOutcome(plan, capture, "", Usage(), 0, cached=True)
        if self.describe is not None and image.get("key"):
            image = {**image, **self.describe(image["key"])}
        usage = Usage()
        problems: list[str] = []
        log, session_id = "", None
        for attempt in range(self.fix_rounds + 1):
            remaining = budget_usd - usage.cost_usd
            if remaining <= 0:
                raise BudgetExceeded(usage.cost_usd, budget_usd)
            resp = await self.planner.plan(
                PlanRequest(script, research, brief, image, attempt, problems, log, session_id, remaining)
            )
            usage, session_id, plan = usage + resp.usage, resp.session_id, resp.plan
            problems = plan_issues(plan, script)
            if not problems:
                key = capture_key(plan, script, image["key"])
                async with transaction(self.sm) as s:
                    hit = await s.get(CaptureCache, key)
                if hit is not None:
                    return CaptureOutcome(plan, hit.capture, hit.log, usage, attempt, cached=True)
                try:
                    capture, log = await self.runner.run(plan, script, run_id)
                except CaptureFailure as exc:
                    if exc.code == "version_mismatch":
                        raise CaptureBlocked("version_mismatch", str(exc)) from exc
                    problems, log = [str(exc)], exc.log
                else:
                    problems = check_values(capture)
                    if not problems:
                        capture = {**capture, "cache_key": key}
                        async with transaction(self.sm) as s:
                            await s.merge(CaptureCache(key=key, capture=capture, log=log))
                        return CaptureOutcome(plan, capture, log, usage, attempt)
        raise CaptureBlocked("not_reproducible", "the capture plan could not be reproduced", problems[:10])


__all__ = [
    "CaptureBlocked", "CaptureFailure", "CaptureOutcome", "CapturePlanner", "CaptureRunner", "CaptureService",
    "PlanRequest", "PlanResponse", "capture_key", "check_values", "plan_issues", "script_commands",
]  # fmt: skip
