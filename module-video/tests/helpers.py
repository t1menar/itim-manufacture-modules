"""Shared builders and fakes for B2 tests."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from mvideo.core_client import (
    CoreRejected,
    CoreUnavailable,
    Credential,
    CredentialError,
    JobCall,
)

DIGEST = "sha256:" + "a" * 64


def settings_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "agent": {"image": f"video-agent@{DIGEST}"},
        "sandbox_images": {
            "postgres17": {
                "image": f"postgres:17@{DIGEST}",
                "ready_cmd": "pg_isready -U postgres",
                "version_cmd": "psql -U postgres -tAc 'SELECT version()'",
                "version_expect": "PostgreSQL 17.",
                "sessions": {"psql": {"kind": "psql", "start": "psql -X -U postgres -d {database}"}},
            }
        },
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(values.get(key), dict):
            values[key] = {**values[key], **val}
        else:
            values[key] = val
    return values


def job_request(
    *,
    job_id: uuid.UUID | None = None,
    production_id: uuid.UUID | None = None,
    attempt: int = 1,
    mode: str = "create",
    deadline: dt.datetime | None = None,
    settings: dict[str, Any] | None = None,
    idea_ref: dict[str, int] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    jid = job_id or uuid.uuid4()
    body: dict[str, Any] = {
        "job_id": str(jid),
        "attempt": attempt,
        "production_id": str(production_id or uuid.uuid4()),
        "stage": "video",
        "mode": mode,
        "variant": None,
        "input": {
            "idea_ref": idea_ref or {"id": 42, "rev": 1},
            "channels": [{"id": "itim", "language": "en", "name": "iTim", "settings": {}}],
        },
        "settings": {"version": 7, "values": settings if settings is not None else settings_values()},
        "credentials": ["cred:claude-subscription"],
        "callback": {"base_url": f"http://core:8080/internal/v1/jobs/{jid}"},
        "deadline": (deadline or dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
    }
    body.update(overrides)
    return body


class FakeCore:
    """Records what the module sends to the core; failures can be switched on per test."""

    def __init__(self) -> None:
        self.progress_calls: list[tuple[str, int, str]] = []
        self.results: list[tuple[str, dict[str, Any]]] = []
        self.fails: list[tuple[str, dict[str, Any]]] = []
        self.credential_reads: list[str] = []
        self.credential_kind = "claude_oauth_token"
        self.credential_error: str | None = None  # not_found | forbidden
        self.result_error: Exception | None = None
        self.progress_error: Exception | None = None

    async def progress(self, call: JobCall, percent: int, step: str, message: str) -> None:
        if self.progress_error is not None:
            raise self.progress_error
        self.progress_calls.append((call.job_id, percent, step))

    async def result(self, call: JobCall, body: dict[str, Any]) -> None:
        if self.result_error is not None:
            raise self.result_error
        self.results.append((call.job_id, body))

    async def fail(self, call: JobCall, body: dict[str, Any]) -> None:
        self.fails.append((call.job_id, body))

    async def get_credential(self, call: JobCall, ref: str) -> Credential:
        self.credential_reads.append(ref)
        if self.credential_error is not None:
            raise CredentialError(self.credential_error, ref)
        return Credential(ref=ref, kind=self.credential_kind, value="secret-token-value")


__all__ = ["CoreRejected", "CoreUnavailable", "FakeCore", "job_request", "settings_values"]


async def seed_idea(
    factory: Any,
    *,
    idea_id: int = 42,
    rev: int = 1,
    title: str = "Why CREATE DATABASE copies a template",
    status: str = "dispatched",
    priority: int = 0,
    active_topic: bool = True,
    topic_code: str = "postgres_internals",
    **fields: Any,
) -> None:
    """Insert a topic and an idea with a fixed id and rev (idempotent)."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from mvideo.db.models import Idea, IdeaRevision, Topic
    from tests import refdata

    async with factory() as s, s.begin():
        await s.execute(
            pg_insert(Topic)
            .values(code=topic_code, title="PostgreSQL internals", default_tags=["postgresql"],
                    default_platforms=["instagram"], active=active_topic)
            .on_conflict_do_nothing(index_elements=["code"])
        )  # fmt: skip
        topic_id = (await s.execute(select(Topic.id).where(Topic.code == topic_code))).scalar_one()
        values = {
            "id": idea_id, "topic_id": topic_id, "title": title, "description": "It copies template1.",
            "language": "en", "priority": priority, "status": status, "rev": rev, **fields,
        }  # fmt: skip
        await s.execute(pg_insert(Idea).values(**values).on_conflict_do_nothing(index_elements=["id"]))
        # older revisions exist only as snapshots, as in production
        doc = refdata.idea_document(id=idea_id, rev=rev, idea_ref=f"idea:{idea_id}:v{rev}", title=title)
        await s.execute(
            pg_insert(IdeaRevision)
            .values(idea_id=idea_id, rev=rev, document=doc)
            .on_conflict_do_nothing(index_elements=["idea_id", "rev"])
        )
