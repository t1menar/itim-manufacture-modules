"""Runtime prompts: `prompts/<step>/<version>/{CLAUDE.md, task.md, meta.json}` (06 section 1).

The files are copied verbatim from the reviewed spec by `scripts/extract_prompts.js`; code never
edits their text. Task templates use `{name}` placeholders; an unknown or missing placeholder fails
the step before any token is spent.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class PromptError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Prompt:
    step: str
    version: str
    claude_md: str
    task_md: str
    placeholders: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.step}@{self.version}"

    @property
    def sha256(self) -> str:
        return digest(self.claude_md, self.task_md)


def digest(claude_md: str, task_md: str = "") -> str:
    return hashlib.sha256(f"{claude_md}\0{task_md}".encode()).hexdigest()


def placeholders_of(template: str) -> list[str]:
    return sorted(set(PLACEHOLDER.findall(template)))


def load_prompt(step: str, version: str, root: Path = PROMPTS_ROOT) -> Prompt:
    d = root / step / version
    if not (d / "CLAUDE.md").is_file():
        raise PromptError(f"prompt {step}@{version} not found in {root}")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    claude = (d / "CLAUDE.md").read_text(encoding="utf-8")
    task = (d / "task.md").read_text(encoding="utf-8")
    return Prompt(step, version, claude, task, tuple(meta["placeholders"]))


def load_skill(version: str = "1.0.0", root: Path = PROMPTS_ROOT) -> str:
    return (root / "skill" / version / "SKILL.md").read_text(encoding="utf-8")


def render(template: str, values: Mapping[str, object]) -> str:
    """Strict `{name}` substitution: unknown and missing names raise; values go in as plain text."""
    names = set(PLACEHOLDER.findall(template))
    missing = sorted(names - set(values))
    if missing:
        raise PromptError(f"missing placeholder values: {', '.join(missing)}")
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)


SEMVER = re.compile(r"^[0-9]+\.[0-9]{1,2}\.[0-9]{1,2}$")  # minor and patch below 100: see semver_number
ACTIVE = "active"


def semver_number(version: str) -> int:
    """`MAJOR.MINOR.PATCH` as one integer (`1.0.1` -> 10001): the core wants an integer in prompt_refs.

    The semver itself stays in `prompt_id` (`analysis@1.0.1`). Minor and patch are below 100.
    """
    major, minor, patch = semver_key(version)
    return major * 10_000 + minor * 100 + patch


def semver_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


class PromptStore:
    """Prompts from database `video` (editable, immutable versions) with the packaged files as the seed.

    `factory=None` reads the files only (tests and tools without a database). `"active"` as a version
    resolves to the activated version of the step.
    """

    def __init__(self, factory: Any = None, root: Path = PROMPTS_ROOT) -> None:
        self._factory = factory
        self._root = root

    async def resolve(self, step: str, version: str) -> str:
        if version != ACTIVE:
            return version
        if self._factory is None:
            versions = sorted(
                (p.name for p in (self._root / step).iterdir() if SEMVER.match(p.name)), key=semver_key
            )
            if not versions:
                raise PromptError(f"no prompt versions of {step!r}")
            return versions[-1]
        from mvideo.db import prompts_repo

        async with self._factory() as s:
            active = await prompts_repo.get_active(s, step)
        if active is None:
            raise PromptError(f"no active prompt version for {step!r}")
        return str(active.version)

    async def get(self, step: str, version: str) -> Prompt:
        version = await self.resolve(step, version)
        if self._factory is None:
            return (
                load_skill_prompt(version, self._root)
                if step == "skill"
                else load_prompt(step, version, self._root)
            )
        from mvideo.db import prompts_repo

        async with self._factory() as s:
            row = await prompts_repo.get_version(s, step, version)
        if row is None:
            raise PromptError(f"prompt {step}@{version} not found")
        return Prompt(step, version, row.claude_md, row.task_md, tuple(row.placeholders))


def load_skill_prompt(version: str, root: Path) -> Prompt:
    return Prompt("skill", version, load_skill(version, root), "", ())
