"""Calls from the module to the core (04 section 3): callbacks and credential reads.

Transport note: this is the HTTP contract 1 of core-04. The core is moving job delivery to
RabbitMQ (core-04 section 15); the runner depends only on the small `CoreGateway` shape below,
so a broker-based implementation can replace this class without touching the pipeline.
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import structlog

log = structlog.get_logger()


class CoreRejected(Exception):
    """409: the core no longer wants this job (stale attempt or cancelled). Retrying is pointless."""


class CoreUnavailable(Exception):
    """The core could not be reached or kept answering 5xx until the retry budget ran out."""


class CoreError(Exception):
    """Any other 4xx: a bug or a configuration problem, not retried."""


class CredentialError(Exception):
    def __init__(self, reason: str, ref: str) -> None:
        super().__init__(f"credential {ref}: {reason}")
        self.reason = reason  # not_found | forbidden
        self.ref = ref


@dataclass(frozen=True, slots=True)
class Credential:
    ref: str
    kind: str
    value: str = field(repr=False)  # never logged, never persisted
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class JobCall:
    """What identifies a job towards the core: callback base URL and tracing headers."""

    job_id: str
    production_id: str
    base_url: str
    traceparent: str | None = None


class CoreGateway(Protocol):
    async def progress(self, call: JobCall, percent: int, step: str, message: str) -> None: ...
    async def result(self, call: JobCall, body: dict[str, Any]) -> None: ...
    async def fail(self, call: JobCall, body: dict[str, Any]) -> None: ...
    async def get_credential(self, call: JobCall, ref: str) -> Credential: ...


class CoreClient:
    def __init__(
        self,
        core_url: str,
        token: str,
        *,
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        backoff_base_s: float = 1.0,
        backoff_max_s: float = 60.0,
        give_up_s: float = 900.0,
    ) -> None:
        self._core_url = core_url.rstrip("/")
        self._token = token
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self._owns_http = http is None
        self._sleep = sleep
        self._monotonic = monotonic
        self._base = backoff_base_s
        self._max = backoff_max_s
        self._give_up = give_up_s

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _headers(self, call: JobCall) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Production-Id": call.production_id,
            "X-Job-Id": call.job_id,
        }
        if call.traceparent:
            headers["traceparent"] = call.traceparent
        return headers

    async def _send(
        self, method: str, url: str, call: JobCall, body: dict[str, Any] | None, *, give_up_s: float
    ) -> httpx.Response:
        """Back off 1 s -> 60 s on network errors and 5xx until `give_up_s` elapsed (04 section 3.1)."""
        started = self._monotonic()
        delay = self._base
        while True:
            try:
                resp = await self._http.request(method, url, json=body, headers=self._headers(call))
            except httpx.TransportError as exc:
                failure = f"{type(exc).__name__}"
            else:
                if resp.status_code == 409:
                    raise CoreRejected(f"{method} {url}: 409")
                if resp.status_code >= 500 or resp.status_code == 429:
                    failure = f"HTTP {resp.status_code}"
                elif resp.status_code >= 400:
                    raise CoreError(f"{method} {url}: HTTP {resp.status_code} {resp.text[:200]}")
                else:
                    return resp
            if self._monotonic() - started + delay > give_up_s:
                raise CoreUnavailable(f"{method} {url}: {failure} for {give_up_s:.0f}s")
            log.warning("core_call_retry", url=url, failure=failure, wait_s=delay)
            await self._sleep(delay)
            delay = min(delay * 2, self._max)

    async def progress(self, call: JobCall, percent: int, step: str, message: str) -> None:
        body = {"percent": percent, "step": step, "message": message}
        await self._send("POST", f"{call.base_url}/progress", call, body, give_up_s=10.0)

    async def result(self, call: JobCall, body: dict[str, Any]) -> None:
        await self._send("POST", f"{call.base_url}/result", call, body, give_up_s=self._give_up)

    async def fail(self, call: JobCall, body: dict[str, Any]) -> None:
        await self._send("POST", f"{call.base_url}/fail", call, body, give_up_s=self._give_up)

    async def get_credential(self, call: JobCall, ref: str) -> Credential:
        url = f"{self._core_url}/internal/v1/credentials/{urllib.parse.quote(ref, safe='')}"
        try:
            resp = await self._send("GET", url, call, None, give_up_s=30.0)
        except CoreError as exc:
            text = str(exc)
            if "HTTP 404" in text:
                raise CredentialError("not_found", ref) from exc
            if "HTTP 403" in text or "HTTP 401" in text:
                raise CredentialError("forbidden", ref) from exc
            raise
        data = resp.json()
        return Credential(
            ref=data["ref"], kind=data["kind"], value=data["value"], expires_at=data.get("expires_at")
        )
