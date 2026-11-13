"""Where an episode lives (`~/itim/Reels/<Series>/<NN>-<slug>/`), the stage prompts, and the result files.

The agent writes `factory/script_result.json` (script stage) and `factory/post_result.json` (video stage) into the
episode folder; they are validated here before anything goes to the review.
"""

from __future__ import annotations

import json
import re
import unicodedata
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


def slugify(text: str, max_len: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:max_len].rstrip("-") or "episode"


def series_name(idea: dict[str, Any], reels: Path) -> str:
    """The series folder: the idea's first playlist (or `series` / first tag), matched case-insensitively."""
    raw = (
        idea.get("series") or next(iter(idea.get("playlists") or []), None) or next(iter(idea.get("tags") or []), None)
    )
    raw = str(raw or "General").strip()
    if reels.is_dir():
        for d in reels.iterdir():
            if d.is_dir() and d.name.lower() == raw.lower():
                return d.name
    return raw if raw[:1].isupper() else raw.capitalize()


def new_episode_dir(idea: dict[str, Any], reels: Path) -> Path:
    series = reels / series_name(idea, reels)
    series.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for d in series.iterdir() if d.is_dir() and (m := re.match(r"^(\d{2,3})-", d.name))]
    ep = series / f"{(max(nums) + 1 if nums else 1):02d}-{slugify(str(idea.get('title') or 'episode'))}"
    (ep / "factory").mkdir(parents=True, exist_ok=True)
    (ep / "factory" / "idea.json").write_text(json.dumps(idea, ensure_ascii=False, indent=1))
    return ep


def prompt(name: str, **values: str) -> str:
    text = resources.files("mstudio").joinpath("prompts", f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[a-z_]+\}\}", text)
    if left:
        raise ValueError(f"prompt {name}: unfilled {left}")
    return text


# ---------------------------------------------------------------- result files written by the agent
class Scene(BaseModel):
    title: str
    narration: str = ""


class ScriptResult(BaseModel):
    title: str
    hook: str
    takeaway: str = ""
    duration_s: float = Field(gt=0, le=90)
    scenes: list[Scene] = Field(min_length=3)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list, max_length=5)
    script_path: str


class PostResult(BaseModel):
    title: str
    video: str
    cover: str
    caption: str = Field(min_length=20, max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=5)
    duration_s: float = Field(gt=0, le=90)
    changed: list[str] = Field(default_factory=list)  # revisions: what was redone (caption, cover, video, script)
    summary: str = ""

    @field_validator("caption")
    @classmethod
    def _five_tags(cls, v: str) -> str:
        if len(re.findall(r"(?<![\w#])#\w", v)) > 5:
            raise ValueError("Instagram allows at most 5 hashtags")
        return v


class ResultInvalid(Exception):
    pass


def read_result[M: BaseModel](ep: Path, name: str, model: type[M], since: float = 0.0) -> M:
    path = ep / "factory" / name
    if not path.exists():
        raise ResultInvalid(f"{path} was not written")
    if path.stat().st_mtime < since:
        raise ResultInvalid(f"{path} was not updated in this run")
    try:
        res = model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise ResultInvalid(f"{name} is invalid: {e}") from e
    for f in ("video", "cover", "script_path"):
        p = getattr(res, f, None)
        if p is not None:
            full = Path(p) if Path(p).is_absolute() else ep / p
            if not full.exists():
                raise ResultInvalid(f"{name}: {f} {full} does not exist")
            setattr(res, f, str(full))
    return res
