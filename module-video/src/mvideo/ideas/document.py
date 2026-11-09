"""The idea document (contracts/idea.json): built from idea and topic rows, validated, rendered."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from mvideo.db.models import Idea, Topic
from mvideo.ideas.ids import format_ref

SCHEMA_DIR = Path(__file__).parent / "schemas"


@cache
def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8")))


def schema_errors(name: str, doc: Any) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '/'}: {e.message}" for e in validator(name).iter_errors(doc)
    ]


def build_document(idea: Idea, topic: Topic) -> dict[str, Any]:
    """Idea content and topic as they are now; the caller snapshots it at dispatch."""
    return {
        "id": idea.id,
        "rev": idea.rev,
        "idea_ref": format_ref(idea.id, idea.rev),
        "title": idea.title,
        "description": idea.description,
        "hook": idea.hook,
        "audience": idea.audience,
        "language": idea.language,
        "tags": list(idea.tags or topic.default_tags or []),
        "references": list(idea.references or []),
        "constraints": idea.constraints,
        "priority": idea.priority,
        "pipeline_id": idea.pipeline_id,
        "notes": idea.notes,
        "author": idea.author,
        "topic": {
            "id": topic.id,
            "code": topic.code,
            "title": topic.title,
            "rev": topic.rev,
            "default_tags": list(topic.default_tags or []),
            "default_platforms": list(topic.default_platforms or []),
        },
    }


def idea_text(doc: dict[str, Any]) -> str:
    """The idea as the prompts' `{idea_text}`: title, description, optional guidance lines."""
    lines = [str(doc["title"]), "", str(doc["description"])]
    if doc.get("hook"):
        lines += ["", f"Hook suggested by the owner: {doc['hook']}"]
    if doc.get("audience"):
        lines.append(f"Audience: {doc['audience']}")
    c = doc.get("constraints") or {}
    if c:
        lines.append("Constraints: " + ", ".join(f"{k}={v}" for k, v in c.items()))
    if doc.get("notes"):
        lines.append(f"Notes: {doc['notes']}")
    return "\n".join(lines)
