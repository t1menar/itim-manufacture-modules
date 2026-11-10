"""What the validator reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Issue:
    rule: str  # schema, ids_unique, expect_match, ...
    path: str  # JSON pointer into the file
    message: str
    file: str = ""
    fixable: bool = True  # whether the agent can fix it by editing the file

    def __str__(self) -> str:
        where = f"{self.file}:{self.path}" if self.file else self.path
        return f"[{self.rule}] {where}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "file": self.file, "path": self.path, "message": self.message}


@dataclass(slots=True)
class Report:
    issues: list[Issue] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def rules(self) -> set[str]:
        return {i.rule for i in self.issues}

    def extend(self, issues: list[Issue]) -> None:
        self.issues.extend(issues)
