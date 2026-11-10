"""Core admin HTTP client (D20): mfa_ token + X-Admin-Actor: tg:<id>."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx


class CoreAdminClient:
    """Calls core requireAdmin routes. Never logs the token."""

    def __init__(self, base_url: str, admin_token: str, *, timeout_s: float = 30.0) -> None:
        if not admin_token.startswith("mfa_"):
            raise ValueError("core admin token must use mfa_ prefix")
        self._base = base_url.rstrip("/")
        self._token = admin_token
        self._timeout = timeout_s

    def _headers(self, telegram_user_id: int) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Admin-Actor": f"tg:{telegram_user_id}",
        }

    async def republish(
        self,
        intent_id: UUID,
        *,
        reason: str,
        base_generation: int,
        telegram_user_id: int,
        acknowledge_unknown_risk: bool = False,
        content_revision_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = self._headers(telegram_user_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        body: dict[str, Any] = {
            "reason": reason,
            "base_generation": base_generation,
            "acknowledge_unknown_risk": acknowledge_unknown_risk,
        }
        if content_revision_id is not None:
            body["content_revision_id"] = str(content_revision_id)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{self._base}/internal/v1/publish-intents/{intent_id}/republish",
                headers=headers,
                json=body,
            )

    async def activate_module(
        self, module_id: str, *, telegram_user_id: int, replace: bool = True
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{self._base}/internal/v1/modules/{module_id}/activate",
                headers=self._headers(telegram_user_id),
                json={"replace": replace},
            )

    async def deactivate_module(self, module_id: str, *, telegram_user_id: int) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{self._base}/internal/v1/modules/{module_id}/deactivate",
                headers=self._headers(telegram_user_id),
            )

    async def get_core_settings(self, *, telegram_user_id: int) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.get(
                f"{self._base}/internal/v1/modules/core/settings",
                headers=self._headers(telegram_user_id),
            )

    async def put_core_settings(
        self,
        *,
        values: dict[str, Any],
        base_version: int,
        telegram_user_id: int,
        comment: str = "",
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.put(
                f"{self._base}/internal/v1/modules/core/settings",
                headers=self._headers(telegram_user_id),
                json={"values": values, "base_version": base_version, "comment": comment},
            )

    async def retry_variant(self, variant_id: UUID, *, telegram_user_id: int) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{self._base}/internal/v1/variants/{variant_id}/retry",
                headers=self._headers(telegram_user_id),
            )

    async def skip_variant(self, variant_id: UUID, *, reason: str, telegram_user_id: int) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                f"{self._base}/internal/v1/variants/{variant_id}/skip",
                headers=self._headers(telegram_user_id),
                json={"reason": reason},
            )
