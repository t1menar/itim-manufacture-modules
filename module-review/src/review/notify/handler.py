"""Consume notify.requested (HTTP or AMQP) with inbox dedup and admin fan-out."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from review.db.inbox import try_claim
from review.observability.logging import get_logger
from review.telegram.sender import MessageSender

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
    variant = payload.get("variant_id") or "?"
    pubs = payload.get("publications") or []
    lines = [f"publish:{kind} variant={variant} status={status}"]
    for p in pubs:
        if not isinstance(p, dict):
            continue
        st = p.get("status")
        url = p.get("url") or ""
        err = ""
        detail = p.get("error_detail")
        if isinstance(detail, dict) and detail.get("code"):
            err = f" code={detail.get('code')}"
        elif p.get("error"):
            err = f" err={p.get('error')}"
        lines.append(f"  - {p.get('platform')}:{st} {url}{err}".rstrip())
    return "\n".join(lines)


class NotifyHandler:
    def __init__(
        self,
        sessions: async_sessionmaker[Any],
        sender: MessageSender,
        admin_chat_ids: tuple[int, ...],
    ) -> None:
        self._sessions = sessions
        self._sender = sender
        self._admins = admin_chat_ids

    async def handle(self, message_id: str, payload: dict[str, Any]) -> NotifyResult:
        async with self._sessions() as session, session.begin():
            claimed = await try_claim(session, message_id, "notify.requested")
        if not claimed:
            log.info("notify_duplicate", message_id=message_id)
            return NotifyResult(claimed=False, sent=0, status=str(payload.get("status") or ""), text="")
        text = format_notify_message(payload)
        sent = 0
        for chat_id in self._admins:
            await self._sender.send_message(chat_id, text)
            sent += 1
        if not self._admins:
            log.info("notify_no_admins", message_id=message_id, text=text)
        return NotifyResult(
            claimed=True,
            sent=sent,
            status=str(payload.get("status") or ""),
            text=text,
        )

    async def handle_http(self, session: AsyncSession, body: dict[str, Any]) -> NotifyResult:
        """HTTP twin: dedup by notification_id (stable)."""
        raw_id = body.get("notification_id")
        message_id = str(raw_id) if raw_id else f"body:{hash(json.dumps(body, sort_keys=True))}"
        # validate uuid when present
        if raw_id:
            try:
                UUID(str(raw_id))
            except ValueError:
                message_id = f"body:{hash(json.dumps(body, sort_keys=True))}"
        claimed = await try_claim(session, message_id, "notify.requested")
        if not claimed:
            return NotifyResult(claimed=False, sent=0, status=str(body.get("status") or ""), text="")
        text = format_notify_message(body)
        sent = 0
        for chat_id in self._admins:
            await self._sender.send_message(chat_id, text)
            sent += 1
        return NotifyResult(claimed=True, sent=sent, status=str(body.get("status") or ""), text=text)
