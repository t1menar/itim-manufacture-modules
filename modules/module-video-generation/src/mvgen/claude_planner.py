"""`CapturePlanner` on the Claude Agent SDK: the agent writes the plan, the sandbox runner records the output.

The planner has no tools and no sandbox: it only maps the script's commands and declared captures to a plan
(`manufacture.capture-plan/1`). `plan_issues` and the runner check it, so a wrong plan costs one cheap retry that
resumes the same agent session with the exact problems and the execution log.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any

from mvgen.agent import Usage
from mvgen.capture import PlanRequest, PlanResponse, script_commands

QueryFn = Callable[..., AsyncIterator[Any]]

SYSTEM = (
    "You plan how to record the real output of a terminal session for a short technical video. You only write the "
    "capture plan; a program runs it in a sandbox and returns the real values. Answer with one JSON object and nothing "
    "else."
)
HINT = """\
Write {"format": "manufacture.capture-plan/1", "image": <image key>, "sessions": {name: {kind: psql|sh, database?,
workdir?, open_at_start?}}, "ops": [...]}. ops, in order:
- {"op": "open"|"close", "session"}, {"op": "sleep", "seconds"}, {"op": "setup", "session", "text"} (hidden command),
- {"op": "run", "cmd": <command id of the script>} (run every script command exactly once, in script order),
- {"op": "value", "name", "session", "query", "parse": "single"|"first_line"|"count_lines", "why_equal"}
  for every capture the script declares: why_equal says in one sentence why this query returns exactly the number the
  viewer is told about. Queries must read the system, never compute the answer yourself.
"""
JSON_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    for candidate in (text, *(m.group(1) for m in JSON_RE.finditer(text))):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    a, b = text.find("{"), text.rfind("}")
    if 0 <= a < b:
        try:
            value = json.loads(text[a : b + 1])
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def plan_prompt(r: PlanRequest) -> str:
    if r.attempt > 0 and r.session_id:  # the resumed session already holds the first prompt
        parts = ["The plan did not work. Fix exactly these problems and answer with the whole corrected plan:"]
        parts.append(json.dumps(r.problems, ensure_ascii=False, indent=1))
        if r.execution_log:
            parts.append("EXECUTION LOG (tail):\n" + r.execution_log[-4000:])
        return "\n\n".join(parts)
    cmds = script_commands(r.script)
    parts = [
        "IMAGE:\n" + json.dumps(r.image, ensure_ascii=False, indent=1),
        "SCRIPT COMMANDS (id: text):\n" + json.dumps(cmds, ensure_ascii=False, indent=1),
        "CAPTURES THE SCRIPT DECLARES (name: meaning):\n"
        + json.dumps(r.script.get("captures") or {}, ensure_ascii=False, indent=1),
        "CAPTURE NEEDS FROM THE RESEARCH:\n" + json.dumps(r.research.get("capture_needs") or [], ensure_ascii=False),
    ]
    wishes = {k: v for k, v in r.brief.items() if v and k in {"must_show", "must_avoid", "instructions"}}
    if wishes:
        parts.append("OWNER WISHES:\n" + json.dumps(wishes, ensure_ascii=False))
    parts.append(HINT)
    if r.problems:
        parts.append("PROBLEMS OF THE PREVIOUS ANSWER:\n" + json.dumps(r.problems, ensure_ascii=False, indent=1))
    return "\n\n".join(parts)


class ClaudeCapturePlanner:
    def __init__(self, query: QueryFn | None = None, model: str | None = None, max_turns: int = 4) -> None:
        self._query, self.model, self.max_turns = query, model, max_turns

    async def plan(self, request: PlanRequest) -> PlanResponse:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage  # noqa: PLC0415
        from claude_agent_sdk import query as default_query  # noqa: PLC0415

        query: QueryFn = self._query or default_query
        options = ClaudeAgentOptions(
            system_prompt=SYSTEM, allowed_tools=[], tools=[], permission_mode="dontAsk", max_turns=self.max_turns,
            max_budget_usd=float(request.max_budget_usd), model=self.model, setting_sources=[],
            resume=request.session_id if request.attempt > 0 else None,
        )  # fmt: skip
        result: Any = None
        async for message in query(prompt=plan_prompt(request), options=options):
            if isinstance(message, ResultMessage):
                result = message
        if result is None:
            return PlanResponse({}, Usage(), request.session_id)
        plan = extract_json(result.result or "")
        if plan and "image" not in plan and request.image.get("key"):
            plan["image"] = request.image["key"]
        return PlanResponse(plan, Usage(Decimal(str(result.total_cost_usd or 0))), result.session_id)
