"""Idea status machine. Transitions are explicit; anything else is rejected."""

from __future__ import annotations

from enum import StrEnum


class IdeaStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    DISPATCHED = "dispatched"  # a run was requested, the platform has not started it yet
    IN_PRODUCTION = "in_production"
    DONE = "done"
    FAILED = "failed"
    ARCHIVED = "archived"


ALLOWED: dict[IdeaStatus, frozenset[IdeaStatus]] = {
    IdeaStatus.DRAFT: frozenset({IdeaStatus.QUEUED, IdeaStatus.ARCHIVED}),
    IdeaStatus.QUEUED: frozenset({IdeaStatus.DRAFT, IdeaStatus.DISPATCHED, IdeaStatus.ARCHIVED}),
    IdeaStatus.DISPATCHED: frozenset({IdeaStatus.IN_PRODUCTION, IdeaStatus.DONE, IdeaStatus.FAILED, IdeaStatus.QUEUED}),
    IdeaStatus.IN_PRODUCTION: frozenset({IdeaStatus.DONE, IdeaStatus.FAILED}),
    IdeaStatus.DONE: frozenset({IdeaStatus.ARCHIVED}),
    IdeaStatus.FAILED: frozenset({IdeaStatus.QUEUED, IdeaStatus.DRAFT, IdeaStatus.ARCHIVED}),
    IdeaStatus.ARCHIVED: frozenset({IdeaStatus.DRAFT}),
}

# Statuses that occupy a production slot (see the scheduler's in-flight cap).
IN_FLIGHT = frozenset({IdeaStatus.DISPATCHED, IdeaStatus.IN_PRODUCTION})
# Statuses whose content may be edited without a new revision being a surprise.
EDITABLE = frozenset({IdeaStatus.DRAFT, IdeaStatus.QUEUED, IdeaStatus.FAILED})


class TransitionError(ValueError):
    def __init__(self, src: IdeaStatus, dst: IdeaStatus) -> None:
        super().__init__(f"idea cannot go from {src} to {dst}")
        self.src, self.dst = src, dst


def check_transition(src: IdeaStatus, dst: IdeaStatus) -> None:
    if src == dst:
        return
    if dst not in ALLOWED[src]:
        raise TransitionError(src, dst)
