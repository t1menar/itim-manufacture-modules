"""Periodic heartbeat to the core: without it the core marks the module `down` after 90 s and stops
dispatching jobs to it."""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import structlog

log = structlog.get_logger("heartbeat")

INTERVAL_S = 30.0


class Heartbeat:
    def __init__(self, core_url: str, token: str, *, interval_s: float = INTERVAL_S) -> None:
        self._url = f"{core_url.rstrip('/')}/internal/v1/modules/self/heartbeat"
        self._token = token
        self._interval = interval_s
        self._task: asyncio.Task[None] | None = None

    async def beat(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._url, headers={"Authorization": f"Bearer {self._token}"})
        except httpx.HTTPError:
            log.warning("heartbeat_failed", reason="transport")
            return False
        if resp.status_code >= 300:
            log.warning("heartbeat_failed", status=resp.status_code)
        return resp.status_code < 300

    async def _loop(self) -> None:
        while True:
            await self.beat()
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="core-heartbeat")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
