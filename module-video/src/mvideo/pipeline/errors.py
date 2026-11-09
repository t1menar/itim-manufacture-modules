"""Failure vocabulary of the module (04 section 9)."""

from __future__ import annotations

from typing import Any, Literal

ErrorClass = Literal["transient", "fatal", "blocked"]


class StepError(Exception):
    """A step failed in a way that has a defined class and code."""

    def __init__(
        self,
        error_class: ErrorClass,
        code: str,
        message: str,
        *,
        step: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{error_class} {code}: {message}")
        self.error_class = error_class
        self.code = code
        self.message = message
        self.step = step
        self.details = details or {}

    def fail_body(self) -> dict[str, Any]:
        """Body of POST {callback}/fail."""
        return {
            "class": self.error_class,
            "message": self.message,
            "details": {"code": self.code, "step": self.step, **self.details},
        }


class RunCancelled(Exception):
    """The run was cancelled by request: stop quietly, send no callback."""


class LeaseLost(Exception):
    """Another worker took the lease: stop without touching the run any more."""
