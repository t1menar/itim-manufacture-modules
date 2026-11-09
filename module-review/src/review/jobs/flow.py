"""Review decision flow: send card, approve/reject(+reason), callback to core."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from review.admin.allowlist import AdminAllowlist
from review.clients.core import CoreClient
from review.db import repo
from review.db.models import FINAL
from review.jobs.cards import approve_reject_keyboard, card_caption, extract_meta, stale_keyboard
from review.observability.logging import get_logger
from review.storage.s3_client import load_storage_client
from review.telegram.bot import TelegramBot
from review.telegram.updates import TelegramUpdate

log = get_logger(__name__)


class ReviewFlow:
    def __init__(
        self,
        factory: async_sessionmaker[Any],
        bot: TelegramBot,
        core: CoreClient,
        allowlist: AdminAllowlist,
        admin_chat_ids: tuple[int, ...],
        s3_env_fallback: dict[str, str] | None = None,
    ) -> None:
        self._factory = factory
        self._bot = bot
        self._core = core
        self._allowlist = allowlist
        self._admins = admin_chat_ids
        self._s3_env = s3_env_fallback or {}

    async def deliver_card(self, run_id: uuid.UUID) -> None:
        async with self._factory() as s, s.begin():
            run = await repo.get_run(s, run_id)
            if run is None or run.status in FINAL:
                return
            if run.cancel_requested:
                await self._fail_local(s, run, "cancelled_by_admin")
                return
            title, description, video_ref, language = extract_meta(run.input or {})
            version = run.round if run.round > 0 else 1
            caption = card_caption(title=title, description=description, version=version, language=language)
            variant_id = run.variant_id or uuid.uuid4()
            prev = await repo.latest_card(s, variant_id)
            reply_to = prev.message_id if prev is not None else None
            prev_chat = prev.chat_id if prev is not None else None
            prev_mid = prev.message_id if prev is not None else None
            callback = run.callback_base_url
            fence = run.fence
            job_id_s = str(run.job_id)
            chat_id = self._admins[0] if self._admins else 0
            if video_ref.startswith("s3://"):
                storage = await load_storage_client(s, env_fallback=self._s3_env)
                if storage is not None:
                    video_ref = storage.resolve_https(video_ref, ttl_s=3600, public=True)
            if chat_id == 0:
                await repo.store_outcome(
                    s,
                    run.id,
                    status="failed",
                    error={
                        "class": "fatal",
                        "message": "no admin chat configured",
                        "details": {"code": "no_admin"},
                    },
                )
                return

        sent = await self._bot.send_video(
            chat_id,
            video_ref,
            caption=caption,
            reply_to_message_id=reply_to,
            allow_sending_without_reply=True,
            reply_markup=approve_reject_keyboard(job_id_s),
        )
        if prev_chat is not None and prev_mid is not None:
            await self._bot.edit_message_reply_markup(prev_chat, prev_mid, stale_keyboard())

        async with self._factory() as s, s.begin():
            await repo.save_card(
                s,
                run_id=run_id,
                variant_id=variant_id,
                version=version,
                chat_id=chat_id,
                message_id=int(sent["message_id"]),
            )
            await repo.set_status(s, run_id, "awaiting_decision", step="awaiting_decision")
        if callback:
            try:
                await self._core.progress(callback, fence, {"percent": 20, "step": "awaiting_decision"})
            except Exception:
                log.warning("progress_failed")

    async def handle_update(self, upd: TelegramUpdate) -> None:
        if not self._allowlist.contains(upd.user_id):
            return
        if upd.callback_data:
            await self._on_callback(upd)
            return
        if upd.text:
            await self._on_text(upd)

    async def _on_callback(self, upd: TelegramUpdate) -> None:
        data = upd.callback_data or ""
        if upd.callback_query_id:
            with contextlib.suppress(Exception):
                await self._bot.answer_callback_query(upd.callback_query_id)
        if data == "noop" or not data.startswith(("approve:", "reject:")):
            return
        action, _, raw_id = data.partition(":")
        try:
            job_id = uuid.UUID(raw_id)
        except ValueError:
            return

        async with self._factory() as s, s.begin():
            run = await repo.get_run_by_job(s, job_id)
            if run is None or run.status in FINAL or run.status == "succeeded":
                return
            status = run.status
            run_id = run.id
            if action not in {"approve", "reject"}:
                return
            if status != "awaiting_decision":
                return
            snapshot = _run_snapshot(run)

        if action == "reject":
            asked = await self._bot.send_message(
                upd.chat_id,
                "Что не так в ролике? Напишите причину одним сообщением (можно ответом на карточку).",
                reply_to_message_id=upd.callback_message_id,
                allow_sending_without_reply=True,
            )
            async with self._factory() as s, s.begin():
                await repo.set_pending_reject(
                    s,
                    run_id=run_id,
                    chat_id=upd.chat_id,
                    admin_user_id=upd.user_id,
                    card_message_id=upd.callback_message_id,
                    asked_message_id=int(asked["message_id"]),
                )
                await repo.set_status(s, run_id, "awaiting_reason", step="awaiting_reason")
            return

        await self._submit_decision(snapshot, decision="approved", reason=None, reviewer_id=upd.user_id)

    async def _on_text(self, upd: TelegramUpdate) -> None:
        text = (upd.text or "").strip()
        if not text or text.startswith("/"):
            return
        snapshot = None
        async with self._factory() as s, s.begin():
            pending = await repo.find_pending_for_admin(s, upd.chat_id, upd.user_id)
            if pending is None and upd.reply_to_message_id is not None:
                run = await repo.run_by_card_message(s, upd.chat_id, upd.reply_to_message_id)
                if run is not None and run.status == "awaiting_reason":
                    pending = await repo.get_pending_reject(s, run.id)
            if pending is None:
                return
            run = await repo.get_run(s, pending.run_id)
            if run is None or run.status != "awaiting_reason":
                return
            await repo.clear_pending_reject(s, run.id)
            snapshot = _run_snapshot(run)
        await self._submit_decision(snapshot, decision="rejected", reason=text, reviewer_id=upd.user_id)

    async def _submit_decision(
        self,
        run: dict[str, Any],
        *,
        decision: str,
        reason: str | None,
        reviewer_id: int,
    ) -> None:
        run_id: uuid.UUID = run["id"]
        callback = run["callback_base_url"]
        fence = run["fence"]
        if callback is None:
            async with self._factory() as s, s.begin():
                await repo.store_outcome(
                    s, run_id, status="failed", error={"class": "fatal", "message": "no callback"}
                )
            return
        output: dict[str, Any] = {
            "decision": decision,
            "reviewer": {"telegram_user_id": reviewer_id},
            "decided_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "round": run["round"] or 1,
        }
        if reason is not None:
            output["reason"] = reason
        body = {"output": output, "artifacts": []}

        card_chat = card_mid = None
        async with self._factory() as s, s.begin():
            # Idempotent: if already terminal, skip callback re-send only when identical.
            current = await repo.get_run(s, run_id)
            if current is not None and current.status == "succeeded":
                return
            await repo.store_outcome(s, run_id, status="succeeded", result={"output": output})
            if run["variant_id"] is not None:
                card = await repo.latest_card(s, run["variant_id"])
                if card is not None:
                    card.stale = True
                    card_chat, card_mid = card.chat_id, card.message_id

        if card_chat is not None and card_mid is not None:
            with contextlib.suppress(Exception):
                await self._bot.edit_message_reply_markup(card_chat, card_mid, stale_keyboard())
        try:
            resp = await self._core.result(callback, fence, body)
            if resp.status_code >= 300:
                log.warning("result_http", status=resp.status_code)
        except Exception:
            log.exception("result_callback_failed")

    async def _fail_local(self, session: Any, run: Any, code: str) -> None:
        body = {"class": "blocked", "message": code, "details": {"code": code}}
        callback, fence = run.callback_base_url, run.fence
        await repo.store_outcome(session, run.id, status="cancelled", error=body)
        if callback:
            with contextlib.suppress(Exception):
                await self._core.fail(callback, fence, body)


def _run_snapshot(run: Any) -> dict[str, Any]:
    return {
        "id": run.id,
        "callback_base_url": run.callback_base_url,
        "fence": run.fence,
        "round": run.round,
        "variant_id": run.variant_id,
        "job_id": run.job_id,
    }
