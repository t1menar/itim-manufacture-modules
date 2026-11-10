from __future__ import annotations

from decimal import Decimal
from typing import Any

from mscenario.agent import AgentRequest, AgentResponse, Usage


class ScriptedAgent:
    """Returns the prepared outputs in order and records every request."""

    def __init__(self, *outputs: dict[str, Any], cost: str = "0.2") -> None:
        self.outputs = list(outputs)
        self.requests: list[AgentRequest] = []
        self.cost = cost

    async def run(self, request: AgentRequest) -> AgentResponse:
        self.requests.append(request)
        out = self.outputs.pop(0)
        return AgentResponse(out, Usage(Decimal(self.cost), {"fake-model": {"input": 10, "output": 5}}))
