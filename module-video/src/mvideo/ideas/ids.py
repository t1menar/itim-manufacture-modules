"""Idea references and stable message ids (D21): the namespace and formats are shared with core."""

from __future__ import annotations

import re
import uuid

MANUFACTURE_NS = uuid.UUID("b7e1f4a0-5c2d-4e8f-9a1b-0c3d5e7f9a1b")
REF = re.compile(r"^idea:([0-9]+):v([0-9]+)$")


def format_ref(idea_id: int, rev: int) -> str:
    return f"idea:{idea_id}:v{rev}"


def parse_ref(ref: str) -> tuple[int, int]:
    m = REF.match(ref)
    if not m:
        raise ValueError(f"not an idea_ref: {ref!r}")
    return int(m.group(1)), int(m.group(2))


def ready_message_id(idea_id: int, rev: int) -> uuid.UUID:
    return uuid.uuid5(MANUFACTURE_NS, format_ref(idea_id, rev))


def status_message_id(idea_id: int, rev: int, status: str, production_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(MANUFACTURE_NS, f"{format_ref(idea_id, rev)}:{status}:{production_id}")
