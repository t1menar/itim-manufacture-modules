"""A failed check is final (`fatal`): retrying the same input cannot change the outcome."""

from __future__ import annotations

from typing import Any


class CheckFailed(Exception):
    def __init__(self, code: str, message: str, checks: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code, self.checks = code, checks or {}
