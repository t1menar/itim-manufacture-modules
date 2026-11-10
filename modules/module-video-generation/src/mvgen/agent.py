"""Shared agent-side types: cost accounting."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class Usage:
    cost_usd: Decimal = Decimal(0)
    tokens: dict[str, dict[str, int]] = field(default_factory=dict)

    def __add__(self, other: Usage) -> Usage:
        merged: dict[str, dict[str, int]] = {m: dict(t) for m, t in self.tokens.items()}
        for model, counts in other.tokens.items():
            slot = merged.setdefault(model, {})
            for k, v in counts.items():
                slot[k] = slot.get(k, 0) + v
        return Usage(self.cost_usd + other.cost_usd, merged)

    def as_dict(self) -> dict[str, Any]:
        return {"cost_usd": str(self.cost_usd), "tokens": self.tokens}


class BudgetExceeded(Exception):
    def __init__(self, spent: Decimal, budget: Decimal) -> None:
        super().__init__(f"video budget exceeded: spent {spent} of {budget} USD")
        self.spent, self.budget = spent, budget
