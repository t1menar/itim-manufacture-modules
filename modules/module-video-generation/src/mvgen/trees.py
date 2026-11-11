"""Source trees for the code citations shown on screen: the pinned commit, read-only, fetched once."""

from __future__ import annotations

import asyncio
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path


class TreeError(Exception):
    pass


class DirTree:
    """`SourceTree` of `mvrender` over a directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _safe(self, path: str) -> Path | None:
        p = (self.root / path).resolve()
        return p if p.is_relative_to(self.root.resolve()) and p.is_file() else None

    def exists(self, path: str) -> bool:
        return self._safe(path) is not None

    def line(self, path: str, n: int) -> str | None:
        p = self._safe(path)
        if p is None:
            return None
        lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
        return lines[n - 1] if 1 <= n <= len(lines) else None


class GitTrees:
    """`TreeProvider`: shallow fetch of one commit, `git archive` into `cache_dir/<hash>`, reused afterwards."""

    def __init__(self, cache_dir: Path | None = None, timeout_s: float = 300) -> None:
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "mvgen-trees"
        self.timeout_s = timeout_s

    async def _git(self, *args: str, cwd: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError as exc:
            proc.kill()
            raise TreeError(f"git {args[0]} timed out") from exc
        if proc.returncode != 0:
            raise TreeError(f"git {args[0]} failed: {err.decode(errors='replace').strip()[:300]}")

    async def open(self, repo: str, commit: str) -> DirTree:
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise TreeError(f"not a full commit id: {commit!r}")
        root = self.cache_dir / sha256(f"{repo}@{commit}".encode()).hexdigest()[:24]
        if (root / ".done").exists():
            return DirTree(root / "tree")
        work = Path(tempfile.mkdtemp(prefix="fetch-", dir=self.cache_dir if self.cache_dir.exists() else None))
        (work / "git").mkdir()
        await self._git("init", "-q", cwd=work / "git")
        await self._git("fetch", "-q", "--depth", "1", repo, commit, cwd=work / "git")
        tar = work / "tree.tar"
        await self._git("archive", "--format=tar", "-o", str(tar), "FETCH_HEAD", cwd=work / "git")
        dest = root / "tree"
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar) as tf:
            tf.extractall(dest, filter="data")
        (root / ".done").write_text(commit)
        return DirTree(dest)
