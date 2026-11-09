"""Read access to the source tree of the explained system (`/src` at `meta.system.commit`)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceTree(Protocol):
    def exists(self, path: str) -> bool: ...

    def line(self, path: str, n: int) -> str | None:
        """Line `n` (1-based) of `path` with tabs kept and no newline, or None if out of range."""
        ...


class DirSource:
    """A checked-out repository on disk.

    `flat=True` also finds files by base name when the full path is missing; this lets tests use a
    directory that only holds the few files a script refers to.
    """

    def __init__(self, root: str | Path, *, flat: bool = False) -> None:
        self.root = Path(root)
        self.flat = flat
        self._cache: dict[Path, list[str]] = {}

    def _find(self, path: str) -> Path | None:
        full = self.root / path
        if full.is_file():
            return full
        if self.flat and (self.root / Path(path).name).is_file():
            return self.root / Path(path).name
        return None

    def exists(self, path: str) -> bool:
        return self._find(path) is not None

    def line(self, path: str, n: int) -> str | None:
        found = self._find(path)
        if found is None or n < 1:
            return None
        if found not in self._cache:
            self._cache[found] = found.read_text(encoding="utf-8", errors="replace").split("\n")
        lines = self._cache[found]
        return lines[n - 1] if n <= len(lines) else None


class MemorySource:
    """In-memory tree: `{path: {line_number: text}}`; used by tests and fixtures."""

    def __init__(self, files: dict[str, dict[int, str]]) -> None:
        self.files = files

    def exists(self, path: str) -> bool:
        return path in self.files

    def line(self, path: str, n: int) -> str | None:
        return self.files.get(path, {}).get(n)
