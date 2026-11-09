"""State machines of 05 section 9."""

from __future__ import annotations

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "accepted": frozenset({"running", "cancelling"}),
    "running": frozenset({"succeeded", "failed", "cancelling"}),
    "cancelling": frozenset({"cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
FINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})

STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "reused"}),
    "running": frozenset({"succeeded", "blocked", "failed", "running"}),  # running -> running: try + 1
    "reused": frozenset(),
    "succeeded": frozenset(),
    "blocked": frozenset(),
    "failed": frozenset(),
    "skipped": frozenset(),
}


class InvalidTransition(Exception):
    pass


def check_run_transition(old: str, new: str) -> None:
    if old == new:
        return
    if new not in RUN_TRANSITIONS.get(old, frozenset()):
        raise InvalidTransition(f"run {old} -> {new}")
