"""Pinned source trees: an allowlist of repositories, a commit that never moves, a read-only checkout."""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class SourceError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Pin:
    repo: str
    ref: str
    commit: str


class SourceTree:
    """Read-only view of a checkout. Paths are relative and must stay inside the root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._lines: dict[str, list[str] | None] = {}

    def _resolve(self, rel: str) -> Path | None:
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            return None
        p = (self.root / rel).resolve()
        return p if p.is_relative_to(self.root) and p.is_file() else None

    def exists(self, rel: str) -> bool:
        return self._resolve(rel) is not None

    def lines(self, rel: str) -> list[str] | None:
        if rel not in self._lines:
            p = self._resolve(rel)
            self._lines[rel] = p.read_text(errors="replace").splitlines() if p else None
        return self._lines[rel]

    def line(self, rel: str, n: int) -> str | None:
        lines = self.lines(rel)
        return lines[n - 1] if lines is not None and 1 <= n <= len(lines) else None


def normalize_repo(url: str) -> str:
    u = url.strip().rstrip("/")
    return u.removesuffix(".git").lower() if u.startswith(("http://", "https://")) else u


def allowed_pin_source(repo: str, ref: str, allowed: Sequence[Any]) -> bool:
    """`allowed` entries are a URL string or {"repo": url, "refs": [..]}; no refs means any ref."""
    for entry in allowed:
        if isinstance(entry, str):
            e_repo, refs = entry, []
        elif isinstance(entry, dict) and "repo" in entry:
            e_repo, refs = str(entry["repo"]), list(entry.get("refs") or [])
        else:
            continue
        if normalize_repo(e_repo) == normalize_repo(repo) and (not refs or ref in refs):
            return True
    return False


class SourceProvider(Protocol):
    async def checkout(self, repo: str, ref: str) -> tuple[Pin, SourceTree]: ...


class GitSourceProvider:
    """Shallow fetch of one ref into a throw-away directory and `git archive` into a read-only tree."""

    def __init__(self, work_dir: Path | None = None, timeout_s: float = 300) -> None:
        self.work_dir = work_dir
        self.timeout_s = timeout_s

    async def _git(self, *args: str, cwd: Path | None = None) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError as e:
            proc.kill()
            raise SourceError(f"git {args[0]} timed out") from e
        if proc.returncode != 0:
            raise SourceError(f"git {args[0]} failed: {err.decode(errors='replace').strip()[:300]}")
        return out.decode()

    async def checkout(self, repo: str, ref: str) -> tuple[Pin, SourceTree]:
        base = Path(tempfile.mkdtemp(prefix="mscenario-", dir=self.work_dir))
        git_dir, tree_dir = base / "git", base / "tree"
        git_dir.mkdir()
        tree_dir.mkdir()
        await self._git("init", "-q", cwd=git_dir)
        await self._git("fetch", "-q", "--depth", "1", repo, ref, cwd=git_dir)
        commit = (await self._git("rev-parse", "FETCH_HEAD^{commit}", cwd=git_dir)).strip()
        if not SHA_RE.match(commit):
            raise SourceError(f"unexpected commit id {commit!r}")
        tar = base / "tree.tar"
        await self._git("archive", "--format=tar", "-o", str(tar), commit, cwd=git_dir)
        proc = await asyncio.create_subprocess_exec("tar", "-xf", str(tar), "-C", str(tree_dir))
        if await proc.wait() != 0:
            raise SourceError("could not unpack the archive")
        tar.unlink()
        return Pin(repo, ref, commit), SourceTree(tree_dir)
