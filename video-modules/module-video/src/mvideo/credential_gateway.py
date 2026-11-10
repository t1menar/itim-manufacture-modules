"""Credentials: the module database first, the core as the fallback."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from mvideo.core_client import CoreGateway, Credential, JobCall
from mvideo.db import credentials_repo


class LocalCredentialGateway:
    """A `CoreGateway` that serves credentials stored in this module and forwards the rest."""

    def __init__(self, core: CoreGateway, factory: async_sessionmaker[Any]) -> None:
        self._core = core
        self._factory = factory

    async def progress(self, call: JobCall, percent: int, step: str, message: str) -> None:
        await self._core.progress(call, percent, step, message)

    async def result(self, call: JobCall, body: dict[str, Any]) -> None:
        await self._core.result(call, body)

    async def fail(self, call: JobCall, body: dict[str, Any]) -> None:
        await self._core.fail(call, body)

    async def get_credential(self, call: JobCall, ref: str) -> Credential:
        async with self._factory() as s:
            row = await credentials_repo.get(s, ref)
        if row is not None:
            return Credential(ref=row.ref, kind=row.kind, value=row.value)
        return await self._core.get_credential(call, ref)
