from __future__ import annotations

from pathlib import Path

import pytest

from mscenario.sources import GitSourceProvider, SourceError


async def test_checkout_pins_a_commit_and_exposes_lines(repo: str, tmp_path: Path) -> None:
    pin, tree = await GitSourceProvider(work_dir=tmp_path).checkout(repo, "main")
    assert len(pin.commit) == 40 and pin.ref == "main"
    assert tree.line("src/main.c", 3).strip() == "plan_query();"  # type: ignore[union-attr]
    assert tree.line("src/main.c", 99) is None
    assert tree.line("../x", 1) is None
    assert not (tree.root / ".git").exists()


async def test_unknown_ref_fails_cleanly(repo: str, tmp_path: Path) -> None:
    with pytest.raises(SourceError):
        await GitSourceProvider(work_dir=tmp_path).checkout(repo, "no-such-branch")
