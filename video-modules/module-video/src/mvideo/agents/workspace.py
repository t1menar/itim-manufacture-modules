"""Agent workspace: files for /work, /in, /ref and /job as tar archives (05 section 4, step 1)."""

from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass, field
from typing import Any


def tar_of(files: dict[str, bytes]) -> bytes:
    """A tar archive of `{path: content}`; owner uid 10001 (the agent user), mode 0644, fixed mtime."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for path in sorted(files):
            info = tarfile.TarInfo(path)
            info.size = len(files[path])
            info.mode = 0o644
            info.uid = info.gid = 10001
            info.mtime = 0
            tf.addfile(info, io.BytesIO(files[path]))
    return buf.getvalue()


def untar(data: bytes) -> dict[str, bytes]:
    """Regular files of a tar stream by path relative to the archived directory."""
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                f = tf.extractfile(m)
                if f is not None:
                    out["/".join(m.name.split("/")[1:])] = f.read()
    return out


@dataclass(slots=True)
class Workspace:
    """Everything a step needs on disk. `work` holds CLAUDE.md, the skill and task.md."""

    work: dict[str, bytes] = field(default_factory=dict)
    inputs: dict[str, bytes] = field(default_factory=dict)
    ref: dict[str, bytes] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        claude_md: str,
        task_md: str,
        skill_md: str | None = None,
        skill_name: str = "explainer-video",
        inputs: dict[str, bytes] | None = None,
        ref: dict[str, bytes] | None = None,
    ) -> Workspace:
        work = {"CLAUDE.md": claude_md.encode(), "task.md": task_md.encode()}
        if skill_md is not None:
            work[f".claude/skills/{skill_name}/SKILL.md"] = skill_md.encode()
        return cls(work, dict(inputs or {}), dict(ref or {}))


def run_json(
    *,
    model: str,
    max_turns: int,
    max_budget_usd: float | None,
    allowed_tools: list[str],
    disallowed_tools: list[str],
    permission_mode: str,
    setting_sources: list[str],
    prompt: str,
    resume: str | None = None,
    mcp_servers: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    reading_wps: float | None = None,
) -> bytes:
    """The `/job/run.json` read by the runner. Never contains credentials."""
    body = {
        "cwd": "/work", "model": model, "max_turns": max_turns, "max_budget_usd": max_budget_usd,
        "allowed_tools": allowed_tools, "disallowed_tools": disallowed_tools,
        "permission_mode": permission_mode, "setting_sources": setting_sources, "prompt": prompt,
        "resume": resume, "mcp_servers": mcp_servers or {}, "settings": settings or {},
        "reading_wps": reading_wps,
    }  # fmt: skip
    return json.dumps(body, ensure_ascii=False).encode()
