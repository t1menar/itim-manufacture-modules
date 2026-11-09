"""Runtime prompts: `prompts/<step>/<version>/{CLAUDE.md, task.md, meta.json}` (06 section 1).

The files are copied verbatim from the reviewed spec by `scripts/extract_prompts.js`; code never
edits their text. Task templates use `{name}` placeholders; an unknown or missing placeholder fails
the step before any token is spent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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
