from __future__ import annotations

import tomllib
from pathlib import Path

import mvideo
import mvrender


def test_versions_agree() -> None:
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert mvideo.__version__ == pyproject["project"]["version"] == mvrender.__version__
