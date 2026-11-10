"""Credentials stored in the module database."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mvideo.db.models import StoredCredential


async def put(s: AsyncSession, ref: str, kind: str, value: str, *, note: str | None, actor: str) -> bool:
    """Create or replace; returns True when the credential is new."""
    row = await s.get(StoredCredential, ref)
    now = dt.datetime.now(dt.UTC)
    if row is None:
        s.add(StoredCredential(ref=ref, kind=kind, value=value, note=note, updated_by=actor))
        return True
    row.kind, row.value, row.note, row.updated_by, row.updated_at = kind, value, note, actor, now
    return False


async def get(s: AsyncSession, ref: str) -> StoredCredential | None:
    return await s.get(StoredCredential, ref)


async def refs(s: AsyncSession) -> set[str]:
    return set((await s.execute(select(StoredCredential.ref))).scalars())


async def list_meta(s: AsyncSession) -> list[dict[str, Any]]:
    rows = (await s.execute(select(StoredCredential).order_by(StoredCredential.ref))).scalars()
    return [
        {
            "ref": r.ref, "kind": r.kind, "note": r.note, "updated_by": r.updated_by,
            "updated_at": r.updated_at.isoformat(), "length": len(r.value),
        }
        for r in rows
    ]  # fmt: skip


async def delete_one(s: AsyncSession, ref: str) -> bool:
    res = await s.execute(delete(StoredCredential).where(StoredCredential.ref == ref))
    return bool(res.rowcount)
