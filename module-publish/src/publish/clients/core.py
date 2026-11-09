"""HTTP client for Core internal callbacks (contract 1). Fence header required."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx


class CoreClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_s

    def _headers(self, *, fence: int | None = None, job_id: UUID | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if fence is not None:
            headers["X-Fence"] = str(fence)
        if job_id is not None:
            headers["X-Job-Id"] = str(job_id)
        return headers

    async def progress(self, callback_base_url: str, fence: int, body: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{callback_base_url.rstrip('/')}/progress",
                headers=self._headers(fence=fence),
                json=body,
            )

    async def result(self, callback_base_url: str, fence: int, body: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{callback_base_url.rstrip('/')}/result",
                headers=self._headers(fence=fence),
                json=body,
            )

    async def fail(self, callback_base_url: str, fence: int, body: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{callback_base_url.rstrip('/')}/fail",
                headers=self._headers(fence=fence),
                json=body,
            )

    async def heartbeat(self) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{self._base}/internal/v1/modules/self/heartbeat",
                headers=self._headers(),
            )

    async def get_settings(self, etag: str | None = None) -> httpx.Response:
        headers = self._headers()
        if etag:
            headers["If-None-Match"] = etag
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.get(
                f"{self._base}/internal/v1/modules/self/settings",
                headers=headers,
            )

    async def get_credential(self, ref: str, *, job_id: UUID | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.get(
                f"{self._base}/internal/v1/credentials/{ref}",
                headers=self._headers(job_id=job_id),
            )
