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
from publish.instagram.base import InstagramClient, PublishFencedError, UnknownOutcomeError
from publish.instagram.real import InstagramAPIError
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
        publish_margin_s: float = 30.0,
    ) -> None:
        self._factory = factory
        # media_publish is not started this close to the job deadline: core times the job out at
        # the deadline and retries it, a late publish would race the retry.
        self._publish_margin = dt.timedelta(seconds=publish_margin_s)
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
                    error={
                        "class": "fatal",
                        "message": "internal runner crash",
                        "details": {"code": "internal"},
                    },
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
            variant_id = run.variant_id

        if callback is None:
            async with self._factory() as s, s.begin():
                await repo.store_outcome(
                    s,
                    run_id,
                    status="failed",
                    error={
                        "class": "fatal",
                        "message": "missing callback",
                        "details": {"code": "callback_missing"},
                    },
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
        # D23: resolve platform accounts from module-publish DB when Core left them null.
        channel_ids: list[str] = []
        for ch in payload_input.get("channels") or []:
            if isinstance(ch, dict) and ch.get("id"):
                channel_ids.append(str(ch["id"]))
            elif isinstance(ch, str):
                channel_ids.append(ch)
        async with self._factory() as s:
            accounts = await repo.list_enabled_accounts(s, channel_ids=channel_ids or None)
        account_by_channel: dict[str, list[Any]] = {}
        for acc in accounts:
            account_by_channel.setdefault(acc.channel_id, []).append(acc)
        default_accounts = accounts

        normalized: list[dict[str, Any]] = []
        for raw in intents:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            if item.get("platform_account_id"):
                normalized.append(item)
                continue
            # Expand one core orchestration intent across local accounts for the job channels.
            chosen = default_accounts
            if channel_ids:
                chosen = []
                for cid in channel_ids:
                    chosen.extend(account_by_channel.get(cid, []))
            if not chosen:
                item["platform_account_id"] = item.get("account_id") or str(
                    item.get("intent_id") or uuid.uuid4()
                )
                normalized.append(item)
                continue
            for acc in chosen:
                expanded = dict(item)
                expanded["platform_account_id"] = str(acc.id)
                expanded["handle"] = acc.handle
                expanded["platform"] = acc.platform
                expanded["channel_id"] = acc.channel_id
                normalized.append(expanded)

        await self._progress(run_id, callback, fence, 40, "publish")
        publications: list[dict[str, Any]] = []
        try:
            for index, item in enumerate(normalized):
                if run_id in self._cancel:
                    await self._fail(run_id, callback, fence, "blocked", "cancelled", "cancelled_by_admin")
                    return
                if not await renew():
                    return
                if self._clock() > deadline - self._publish_margin:
                    await self._fail(run_id, callback, fence, "transient", "deadline exceeded", "timeout")
                    return
                pub = await self._publish_one(
                    run_id=run_id,
                    job_id=job_id,
                    fence=fence,
                    deadline=deadline,
                    index=index,
                    item=item,
                    artifact=artifact,
                )
                publications.append(pub)
        except PublishFencedError as exc:
            # Timed out / superseded / cancelled right before media_publish: nothing was sent.
            # A superseded run stays silent (core already moved on); the others report.
            log.warning("publish_fenced", run_id=str(run_id), reason=exc.reason)
            if exc.reason == "superseded":
                return
            if exc.reason == "cancelled":
                await self._fail(run_id, callback, fence, "blocked", "cancelled", "cancelled_by_admin")
            else:
                await self._fail(run_id, callback, fence, "transient", "deadline exceeded", "timeout")
            return
        except Exception as exc:
            await self._fail(run_id, callback, fence, "transient", str(exc), "instagram_error")
            return

        # D23: mirror orchestration outcomes into module-publish.publish_intents (best-effort).
        variant_raw = variant_id
        try:
            async with self._factory() as s, s.begin():
                for item, pub in zip(normalized, publications, strict=False):
                    try:
                        intent_uuid = uuid.UUID(str(item.get("intent_id")))
                        account_uuid = uuid.UUID(str(pub.get("platform_account_id")))
                    except (TypeError, ValueError):
                        continue
                    # Skip when the account is not in the local registry (tests / opaque ids).
                    if await repo.get_platform_account(s, account_uuid) is None:
                        continue
                    rev_raw = item.get("content_revision_id")
                    try:
                        rev_uuid = uuid.UUID(str(rev_raw)) if rev_raw else None
                    except (TypeError, ValueError):
                        rev_uuid = None
                    gen = int(item.get("generation") or 1)
                    published_at = None
                    if pub.get("published_at"):
                        try:
                            published_at = dt.datetime.fromisoformat(
                                str(pub["published_at"]).replace("Z", "+00:00")
                            )
                        except ValueError:
                            published_at = None
                    await repo.upsert_local_intent(
                        s,
                        intent_id=intent_uuid,
                        variant_id=variant_raw,
                        platform_account_id=account_uuid,
                        generation=gen,
                        content_revision_id=rev_uuid,
                        status=str(pub.get("status") or "pending"),
                        external_post_id=pub.get("external_post_id"),
                        url=pub.get("url"),
                        published_at=published_at,
                        last_error=pub.get("error_detail")
                        if isinstance(pub.get("error_detail"), dict)
                        else None,
                    )
        except Exception:
            log.exception("local_intent_mirror_failed", run_id=str(run_id))
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
                    fence=fence,
                )
            return

        async with self._factory() as s, s.begin():
            await repo.store_outcome(
                s, run_id, status="succeeded", result={"output": output}, now=self._clock(), fence=fence
            )
        log.info("run_succeeded", run_id=str(run_id), job_id=str(job_id), pubs=len(publications))

    async def _publish_one(
        self,
        *,
        run_id: uuid.UUID,
        job_id: uuid.UUID,
        fence: int,
        deadline: dt.datetime,
        index: int,
        item: dict[str, Any],
        artifact: Any,
    ) -> dict[str, Any]:
        """Publish one (intent, account) at most once, whatever the retries.

        The publish_ledger row decides: published → return the stored result; publishing/unknown →
        reconcile with Instagram (container status, recent media) and never post again; otherwise
        claim it and post. media_publish is only called after ledger_arm succeeds, which also fences
        out a timed-out, cancelled or superseded run.
        """
        account_id = str(item["platform_account_id"])
        intent_id = str(item.get("intent_id") or "") or None
        intent_key = intent_id or f"job:{job_id}:{index}"
        dry_run = bool(getattr(self._ig, "dry_run", True))
        base = {"platform": "instagram", "platform_account_id": account_id, "intent_id": intent_id}
        if item.get("handle"):
            base["handle"] = item.get("handle")

        def published(external_post_id: str, url: str, at: Any, *, reused: bool = False) -> dict[str, Any]:
            if isinstance(at, dt.datetime):
                at = at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            out = {
                **base,
                "external_post_id": external_post_id,
                "url": url,
                "published_at": at,
                "status": "published",
                "error": None,
                "dry_run": dry_run,
            }
            if reused:
                log.info("publish_reused", intent_key=intent_key, external_post_id=external_post_id)
            return out

        def unknown(message: str) -> dict[str, Any]:
            return {
                **base,
                "status": "unknown",
                "error": message,
                "error_detail": {"code": "publish_outcome_unknown", "retryable": False, "message": message},
            }

        def failed(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
            return {
                **base,
                "status": "failed",
                "error": message,
                "error_detail": {"code": code, "retryable": retryable, "message": message},
            }

        async with self._factory() as s, s.begin():
            row = await repo.ledger_lock(s, intent_key, account_id)
            if row is not None and row.status == "published" and row.external_post_id:
                return published(
                    row.external_post_id,
                    row.url or f"https://www.instagram.com/reel/{row.external_post_id}/",
                    row.published_at or self._clock(),
                    reused=True,
                )
            pending_container = (
                row.container_id if row is not None and row.status in ("publishing", "unknown") else None
            )
            if row is not None and row.status in ("publishing", "unknown") and not pending_container:
                return unknown("earlier publish attempt has no container to reconcile")
            claimed_at = row.claimed_at if row is not None else None
            if pending_container is None:
                await repo.ledger_claim(
                    s,
                    intent_key=intent_key,
                    account_id=account_id,
                    run_id=run_id,
                    fence=fence,
                    caption=artifact.caption,
                    now=self._clock(),
                )

        if pending_container is not None:
            # An earlier attempt reached media_publish: only ask Instagram what happened.
            return await self._reconcile_into_ledger(
                intent_key=intent_key,
                account_id=account_id,
                container_id=pending_container,
                caption=artifact.caption,
                since=claimed_at,
                published=published,
                unknown=unknown,
                failed=failed,
            )

        armed = False

        async def before_publish(container_id: str) -> None:
            nonlocal armed
            async with self._factory() as s, s.begin():
                reason = await repo.ledger_arm(
                    s,
                    intent_key=intent_key,
                    account_id=account_id,
                    run_id=run_id,
                    fence=fence,
                    container_id=container_id,
                    not_after=deadline - self._publish_margin,
                    now=self._clock(),
                )
            if reason is None and run_id in self._cancel:
                reason = "cancelled"
            if reason is not None:
                raise PublishFencedError(reason)
            armed = True

        started = self._clock()
        try:
            result = await self._ig.publish_reel(
                account_id=account_id,
                video_ref=artifact.video_ref,
                caption=artifact.caption,
                cover_ref=artifact.cover_ref,
                intent_id=intent_id,
                before_publish=before_publish,
            )
        except PublishFencedError:
            raise
        except UnknownOutcomeError as exc:
            if not armed:
                # media_publish was never called (e.g. the container poll timed out): nothing posted.
                return failed("instagram_container_timeout", str(exc), retryable=True)
            container_id = exc.external_post_id
            if not container_id:
                async with self._factory() as s, s.begin():
                    await repo.ledger_set(s, intent_key=intent_key, account_id=account_id, status="unknown")
                return unknown(str(exc))
            return await self._reconcile_into_ledger(
                intent_key=intent_key,
                account_id=account_id,
                container_id=container_id,
                caption=artifact.caption,
                since=started,
                published=published,
                unknown=unknown,
                failed=failed,
            )
        except Exception as exc:
            if armed:
                # A definite rejection of media_publish (4xx): nothing was published.
                async with self._factory() as s, s.begin():
                    await repo.ledger_set(
                        s, intent_key=intent_key, account_id=account_id, status="failed", clear_container=True
                    )
            if isinstance(exc, InstagramAPIError):
                return failed(exc.classified.code, str(exc), retryable=exc.classified.retryable)
            return failed("instagram_publish_failed", str(exc), retryable=True)

        async with self._factory() as s, s.begin():
            await repo.ledger_set(
                s,
                intent_key=intent_key,
                account_id=account_id,
                status="published",
                external_post_id=result.external_post_id,
                url=result.url,
                published_at=result.published_at,
            )
        return published(result.external_post_id, result.url, result.published_at)

    async def _reconcile_into_ledger(
        self,
        *,
        intent_key: str,
        account_id: str,
        container_id: str,
        caption: str | None,
        since: dt.datetime | None,
        published: Callable[..., dict[str, Any]],
        unknown: Callable[[str], dict[str, Any]],
        failed: Callable[..., dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            found = await self._ig.reconcile(
                account_id=account_id, external_post_id=container_id, caption=caption, since=since
            )
        except Exception as exc:
            log.warning("reconcile_failed", intent_key=intent_key, error=type(exc).__name__)
            found = None
        status = (found or {}).get("status", "published" if found else None)
        async with self._factory() as s, s.begin():
            if status == "published" and found and found.get("external_post_id"):
                at = found.get("published_at")
                parsed = None
                if isinstance(at, str):
                    try:
                        parsed = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
                    except ValueError:
                        parsed = None
                await repo.ledger_set(
                    s,
                    intent_key=intent_key,
                    account_id=account_id,
                    status="published",
                    external_post_id=str(found["external_post_id"]),
                    url=found.get("url"),
                    published_at=parsed,
                )
                return published(str(found["external_post_id"]), str(found.get("url") or ""), at)
            if status == "not_published":
                await repo.ledger_set(
                    s, intent_key=intent_key, account_id=account_id, status="failed", clear_container=True
                )
                return failed(
                    "instagram_container_failed",
                    f"container {found.get('container_status') if found else ''} was not published",
                    retryable=True,
                )
            await repo.ledger_set(s, intent_key=intent_key, account_id=account_id, status="unknown")
        if status == "published_unverified":
            return unknown("container is published but the media was not matched")
        return unknown("publish outcome unknown after container " + container_id)

    async def _progress(self, run_id: uuid.UUID, callback: str, fence: int, percent: int, step: str) -> None:
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
            await repo.store_outcome(s, run_id, status=status, error=body, now=self._clock(), fence=fence)
