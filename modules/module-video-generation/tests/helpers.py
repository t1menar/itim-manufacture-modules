from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from mvgen.agent import Usage
from mvgen.capture import CaptureFailure, PlanRequest, PlanResponse

REFERENCE = Path(__file__).resolve().parents[3] / "packages" / "mvrender" / "reference" / "create_database"


def load(name: str) -> Any:
    return json.loads((REFERENCE / name).read_text(encoding="utf-8"))


class Tree:
    def __init__(self, root: Path = REFERENCE / "sources") -> None:
        self.root = root

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def line(self, path: str, n: int) -> str | None:
        lines = (self.root / path).read_text(encoding="utf-8").split("\n")
        return lines[n - 1] if 1 <= n <= len(lines) else None


class Trees:
    def __init__(self) -> None:
        self.opened: list[tuple[str, str]] = []

    async def open(self, repo: str, commit: str) -> Tree:
        self.opened.append((repo, commit))
        return Tree()


class ScriptedPlanner:
    """Returns the given plans in order (the last repeats) and records every request."""

    def __init__(self, *plans: dict[str, Any], cost: str = "0.2") -> None:
        self.plans, self.cost, self.requests = list(plans), Decimal(cost), []  # type: ignore[var-annotated]

    async def plan(self, request: PlanRequest) -> PlanResponse:
        self.requests.append(request)
        i = min(len(self.requests) - 1, len(self.plans) - 1)
        return PlanResponse(copy.deepcopy(self.plans[i]), Usage(self.cost, {"m": {"input": 10}}), "sess-1")


class FakeRunner:
    """Returns the recorded reference capture; `fail` lists exceptions raised on the first calls."""

    def __init__(self, capture: dict[str, Any] | None = None, fail: list[CaptureFailure] | None = None) -> None:
        self.capture = capture if capture is not None else load("capture.json")
        self.fail, self.calls = list(fail or []), 0

    async def run(self, plan: dict[str, Any], script: dict[str, Any], run_id: str) -> tuple[dict[str, Any], str]:
        self.calls += 1
        if self.fail:
            raise self.fail.pop(0)
        return copy.deepcopy(self.capture), "log\n"
