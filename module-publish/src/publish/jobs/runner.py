"""Execute a publish run: verify artifacts, Fake/real Instagram, callbacks with X-Fence."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publish.clients.core import CoreClient
from publish.db import repo
from publish.domain.runner import result_callback_body, run_publish_intents
from publish.instagram.base import InstagramClient, UnknownOutcomeError
from publish.observability.logging import get_logger
from publish.storage.artifacts import ArtifactError, verify_content_revision

log = get_logger(__name__)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class JobRunner:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        core: CoreClient,
        ig: InstagramClient,
        owner: str = "publish-worker-1",
        clock: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        self._factory = factory
        self._core = core
        self._ig = ig
        self.owner = owner
        self._clock = clock
        self._cancel: set[uuid.UUID] = set()

    def signal_cancel(self, run_id: uuid.UUID) -> None:
        self._cancel.add(run_id)

    async def execute(self, run_id: uuid.UUID) -> None:
        try:
            await self._execute(run_id)
        except Exception:
            log.exception("run_crashed", run_id=str(run_id))
            async with self._factory() as s, s.begin():
                await repo.store_outcome(
                    s,
                    run_id,
                    status="failed",
                    error={"class": "fatal", "message": "internal runner crash", "details": {"code": "internal"}},
                    now=self._clock(),
                )

    async def _execute(self, run_id: uuid.UUID) -> None:
        async with self._factory() as s, s.begin():
            run = await repo.get_run(s, run_id)
            if run is None:
                return
            job_id, fence = run.job_id, run.fence
            callback = run.callback_base_url
            payload_input = dict(run.input or {})
            deadline = run.deadline
            cancel_requested = run.cancel_requested

        if callback is None:
            async with self._factory() as s, s.begin():
                await repo.store_outcome(
                    s,
                    run_id,
                    status="failed",
                    error={"class": "fatal", "message": "missing callback", "details": {"code": "callback_missing"}},
                    now=self._clock(),
                )
            return

        async def renew() -> bool:
            async with self._factory() as s, s.begin():
                return await repo.renew_lease(s, run_id, self.owner, now=self._clock())

        if not await renew():
            return

        if cancel_requested or run_id in self._cancel:
            await self._fail(run_id, callback, fence, "blocked", "cancelled", "cancelled_by_admin")
            return

        if self._clock() > deadline:
            await self._fail(run_id, callback, fence, "transient", "deadline exceeded", "timeout")
            return

        try:
            artifact = verify_content_revision(
                payload_input.get("upstream") if isinstance(payload_input.get("upstream"), dict) else {},
                list(payload_input.get("intents") or []),
            )
        except ArtifactError as exc:
            await self._fail(run_id, callback, fence, "fatal", exc.message, exc.code)
            return

        await self._progress(run_id, callback, fence, 10, "validate")
        if not await renew():
            return

        intents = list(payload_input.get("intents") or [])
        # Enrich intents with platform_account_id when Core only sent intent_id/content_revision_id.
        # Fake path: platform_account_id may be nested or absent — use intent_id as account key fallback.
        normalized: list[dict[str, Any]] = []
        for raw in intents:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            if not item.get("platform_account_id"):
                item["platform_account_id"] = item.get("account_id") or str(item.get("intent_id") or uuid.uuid4())
            normalized.append(item)

        await self._progress(run_id, callback, fence, 40, "publish")
        publications: list[dict[str, Any]] = []
        try:
            # Prefer domain helper but catch unknown per-intent.
            for item in normalized:
                if run_id in self._cancel:
                    await self._fail(run_id, callback, fence, "blocked", "cancelled", "cancelled_by_admin")
                    return
                if not await renew():
                    return
                if self._clock() > deadline:
                    await self._fail(run_id, callback, fence, "transient", "deadline exceeded", "timeout")
                    return
                account_id = str(item["platform_account_id"])
                intent_id = str(item.get("intent_id") or "") or None
                try:
                    result = await self._ig.publish_reel(
                        account_id=account_id,
                        video_ref=artifact.video_ref,
                        caption=artifact.caption,
                        cover_ref=artifact.cover_ref,
                        intent_id=intent_id,
                    )
                    publications.append(
                        {
                            "platform": "instagram",
                            "platform_account_id": account_id,
                            "handle": item.get("handle"),
                            "external_post_id": result.external_post_id,
                            "url": result.url,
                            "published_at": result.published_at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "status": "published",
                            "error": None,
                            "dry_run": bool(getattr(self._ig, "dry_run", True)),
                            "intent_id": intent_id,
                        }
                    )
                except UnknownOutcomeError as exc:
                    found = None
                    if exc.external_post_id:
                        found = await self._ig.reconcile(
                            account_id=exc.account_id, external_post_id=exc.external_post_id
                        )
                    if found:
                        publications.append(
                            {
                                "platform": "instagram",
                                "platform_account_id": account_id,
                                "external_post_id": found["external_post_id"],
                                "url": found["url"],
                                "published_at": found["published_at"],
                                "status": "published",
                                "intent_id": intent_id,
                                "dry_run": bool(getattr(self._ig, "dry_run", True)),
                            }
                        )
                    else:
                        publications.append(
                            {
                                "platform": "instagram",
                                "platform_account_id": account_id,
                                "status": "unknown",
                                "error": str(exc),
                                "error_detail": {
                                    "code": "publish_outcome_unknown",
                                    "retryable": False,
                                    "message": str(exc),
                                },
                                "intent_id": intent_id,
                            }
                        )
                except Exception as exc:
                    publications.append(
                        {
                            "platform": "instagram",
                            "platform_account_id": account_id,
                            "status": "failed",
                            "error": str(exc),
                            "error_detail": {
                                "code": "instagram_publish_failed",
                                "retryable": True,
                                "message": str(exc),
                            },
                            "intent_id": intent_id,
                        }
                    )
        except Exception as exc:
            await self._fail(run_id, callback, fence, "transient", str(exc), "instagram_error")
            return

        # If helper path unused — still fine; we built publications above.
        _ = run_publish_intents  # kept for unit tests / alternative path

        output = {"publications": publications}
        body = result_callback_body(output, finished_at=self._clock())
        await self._progress(run_id, callback, fence, 90, "callback")
        resp = await self._core.result(callback, fence, body)
        if resp.status_code >= 300:
            log.warning("result_callback_failed", status=resp.status_code, body=resp.text[:200])
            async with self._factory() as s, s.begin():
                await repo.store_outcome(
                    s,
                    run_id,
                    status="failed",
                    error={
                        "class": "transient",
                        "message": f"result callback HTTP {resp.status_code}",
                        "details": {"code": "callback_failed"},
                    },
                    result={"output": output},
                    now=self._clock(),
                )
            return

        async with self._factory() as s, s.begin():
            await repo.store_outcome(
                s, run_id, status="succeeded", result={"output": output}, now=self._clock()
            )
        log.info("run_succeeded", run_id=str(run_id), job_id=str(job_id), pubs=len(publications))

    async def _progress(
        self, run_id: uuid.UUID, callback: str, fence: int, percent: int, step: str
    ) -> None:
        async with self._factory() as s, s.begin():
            await repo.set_progress(s, run_id, percent=percent, step=step)
        try:
            await self._core.progress(callback, fence, {"percent": percent, "step": step})
        except Exception:
            log.warning("progress_callback_failed", step=step)

    async def _fail(
        self,
        run_id: uuid.UUID,
        callback: str,
        fence: int,
        klass: str,
        message: str,
        code: str,
    ) -> None:
        body = {"class": klass, "message": message, "details": {"code": code}}
        try:
            await self._core.fail(callback, fence, body)
        except Exception:
            log.warning("fail_callback_failed", code=code)
        status = "cancelled" if code == "cancelled_by_admin" else "failed"
        async with self._factory() as s, s.begin():
            await repo.store_outcome(s, run_id, status=status, error=body, now=self._clock())
