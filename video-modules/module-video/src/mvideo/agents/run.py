"""One agent invocation with outcome handling and cost: used by the real steps (build prompt B8)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvideo.agents.launcher import AgentLauncher, AgentRequest, AgentResult
from mvideo.agents.outcomes import Outcome, classify, to_error

PRICES = Path(__file__).resolve().parents[3] / "agent" / "prices.json"


@dataclass(frozen=True, slots=True)
class Cost:
    usd: float
    estimated: bool
    tokens_in: int
    tokens_out: int
    cache_read: int = 0
    cache_write: int = 0
    model: str = "default"
    turns: int = 0


def compute_cost(result: dict[str, Any], cost_mode: str, prices: dict[str, Any] | None = None) -> Cost:
    """`usd` mode: the SDK number when present. `estimate` mode (subscription): always from usage."""
    usage = result.get("usage") or {}
    tin = int(usage.get("input_tokens") or 0)
    tout = int(usage.get("output_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    cw = int(usage.get("cache_creation_input_tokens") or 0)
    extra = {"cache_read": cr, "cache_write": cw, "model": result.get("model") or "default",
             "turns": int(result.get("num_turns") or 0)}  # fmt: skip
    reported = result.get("total_cost_usd")
    if cost_mode == "usd" and reported is not None:
        return Cost(float(reported), False, tin, tout, **extra)
    if prices is None:
        prices = json.loads(PRICES.read_text())
    p = prices["models"].get(result.get("model") or "", prices["models"]["default"])
    usd = (
        tin * p["input"] + tout * p["output"]
        + int(usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
        + int(usage.get("cache_creation_input_tokens") or 0) * p["cache_write"]
    ) / 1_000_000  # fmt: skip
    return Cost(round(usd, 4), True, tin, tout, **extra)


async def run_agent(
    launcher: AgentLauncher, req: AgentRequest, on_cost: Callable[[Cost, AgentResult], None] | None = None
) -> tuple[AgentResult, Outcome, Cost]:
    """Run, classify and price; raises the StepError of a failing outcome.

    `on_cost` sees the price of every run, also of one that fails: a run that hit the budget was paid for."""
    res = await launcher.run(req)
    mode = req.settings.resolved_cost_mode()
    outcome = classify(
        res.result, res.names, cost_mode=mode, backoff_s=req.settings.limits.rate_limit_backoff_s
    )
    cost = compute_cost(res.result, mode)
    if on_cost is not None:
        on_cost(cost, res)
    err = to_error(outcome, req.step)
    if err is not None:
        raise err
    return res, outcome, cost
