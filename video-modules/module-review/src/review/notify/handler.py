"""Consume notify.requested with inbox dedup; reply to the approved review card when possible."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.db import repo
from review.db.inbox import try_claim
from review.observability.logging import get_logger
from review.telegram.bot import TelegramBot

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NotifyResult:
    claimed: bool
    sent: int
    status: str
    text: str


def format_notify_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "unknown")
    kind = str(payload.get("attention_kind") or status)
    raw_channel = payload.get("channel")
    channel: dict[str, Any] = raw_channel if isinstance(raw_channel, dict) else {}
    pubs = payload.get("publications") or []
    title = ""
    if isinstance(payload.get("title"), str):
        title = payload["title"]
    lines: list[str] = []
    if kind in {"published", "dry_run"} or status == "published":
        head = f"Опубликовано: {title or 'ролик'}"
        lines.append(head)
        for p in pubs:
            if not isinstance(p, dict) or p.get("status") != "published":
                continue
            where = f"{p.get('platform')} {p.get('handle') or p.get('platform_account_id')}"
            url = p.get("url") or ""
            lines.append(f"→ {where}: {url}".rstrip())
        if len(lines) == 1:
            lines.append(f"(status={status})")
    elif kind in {"partial", "failed", "unknown"} or status in {"partial", "failed"}:
        lines.append(f"Публикация: {kind}/{status}")
        for p in pubs:
            if not isinstance(p, dict):
                continue
            err = ""
            detail = p.get("error_detail")
            if isinstance(detail, dict) and detail.get("code"):
                err = f" [{detail.get('code')}]"
            lines.append(f"- {p.get('platform')}:{p.get('status')}{err}")
    else:
        lines.append(f"publish:{kind} status={status} channel={channel.get('id')}")
    return "\n".join(lines)


class NotifyHandler:
    def __init__(
        self,
        sessions: async_sessionmaker[Any],
        bot: TelegramBot,
        admin_chat_ids: tuple[int, ...],
        registry: Any | None = None,
    ) -> None:
        self._sessions = sessions
        self._bot = bot
        self._admins = admin_chat_ids
        self._registry = registry

    def _default_targets(self) -> list[int]:
        if self._registry is not None and self._registry.chat_id is not None:
            return [self._registry.chat_id]
        return list(self._admins)

    async def _send(self, payload: dict[str, Any], text: str) -> int:
        reply_to = None
        chat_for_reply = None
        raw_variant = payload.get("variant_id")
        if raw_variant:
            try:
                vid = UUID(str(raw_variant))
            except ValueError:
                vid = None
            if vid is not None:
                try:
                    async with self._sessions() as session:
                        card = await repo.latest_card(session, vid)
                        if card is not None:
                            reply_to = card.message_id
                            chat_for_reply = card.chat_id
                except Exception:
                    log.debug("notify_card_lookup_skipped")
        sent = 0
        targets = [chat_for_reply] if chat_for_reply is not None else self._default_targets()
        if not targets:
            targets = self._default_targets()
        for chat_id in targets:
            if chat_id is None:
                continue
            await self._bot.send_message(
                int(chat_id),
                text,
                reply_to_message_id=reply_to if chat_id == chat_for_reply else None,
                allow_sending_without_reply=True,
            )
            sent += 1
        return sent

    async def handle(self, message_id: str, payload: dict[str, Any]) -> NotifyResult:
        async with self._sessions() as session, session.begin():
            claimed = await try_claim(session, message_id, "notify.requested")
        if not claimed:
            log.info("notify_duplicate", message_id=message_id)
            return NotifyResult(claimed=False, sent=0, status=str(payload.get("status") or ""), text="")
        text = format_notify_message(payload)
        sent = await self._send(payload, text)
        if sent == 0:
            log.info("notify_no_admins", message_id=message_id, text=text)
        return NotifyResult(claimed=True, sent=sent, status=str(payload.get("status") or ""), text=text)

    async def handle_http(self, session: AsyncSession, body: dict[str, Any]) -> NotifyResult:
        raw_id = body.get("notification_id")
        message_id = str(raw_id) if raw_id else f"body:{hash(json.dumps(body, sort_keys=True))}"
        if raw_id:
            try:
                UUID(str(raw_id))
            except ValueError:
                message_id = f"body:{hash(json.dumps(body, sort_keys=True))}"
        claimed = await try_claim(session, message_id, "notify.requested")
        if not claimed:
            return NotifyResult(claimed=False, sent=0, status=str(body.get("status") or ""), text="")
        text = format_notify_message(body)
        # send uses its own sessions for card lookup
        sent = await self._send(body, text)
        return NotifyResult(claimed=True, sent=sent, status=str(body.get("status") or ""), text=text)
