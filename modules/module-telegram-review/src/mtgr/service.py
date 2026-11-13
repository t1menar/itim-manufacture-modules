"""ReviewService: two gates, approve/reject, a comment after a reject, and the decision back to the platform.

- one session per gate visit (`step_key` unique): a retried step finds its card, never sends a second;
- Reject asks for the comment; the next text of the owner is the revision instruction and finishes the gate;
- every decision goes to a `DecisionSink` (at-least-once, idempotent by `step_key`); undelivered ones are re-sent;
- rounds per (idea, gate) are capped; past the cap the gate escalates to the operator instead of looping;
- only configured owner chats can decide; stale or repeated taps are answered, never applied twice.
Agent context is not kept here: the owning stage (scenario or video) resumes its own session on the comment.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mtgr.bot import Bot, TelegramError, Update
from mtgr.cards import APPROVE, build_card, parse_callback
from mtgr.db import transaction
from mtgr.models import Event, Seen, Session


@dataclass(frozen=True, slots=True)
class Decision:
    step_key: str
    idea_ref: str
    gate: str
    outcome: str  # approved | rejected | escalated | expired | cancelled
    round: int
    comment: str | None = None
    handle: str | None = None  # `str(ctx.attempt_handle)` of the attempt that waits for this gate


class DecisionSink(Protocol):
    async def decide(self, decision: Decision) -> None:
        """Idempotent by `step_key`: finish the platform's waiting step."""
        ...


@dataclass(frozen=True, slots=True)
class ReviewSettings:
    owners: frozenset[int]
    max_rounds: int = 3
    deadline_h: float = 48.0


@dataclass(frozen=True, slots=True)
class OpenRequest:
    step_key: str
    idea_ref: str
    gate: str  # script | post
    payload: dict[str, Any]
    chat_id: int | None = None  # default: the first owner
    handle: str | None = None  # attempt handle; a retried attempt of the same visit replaces it


IdeaAdder = Callable[[str, str, str], Awaitable[int]]  # (series, title, vision) -> idea id, queued

IDEA_HELP = (
    "Send: /idea Series | Title | your vision\nExample: /idea Postgres | MVCC | two versions of one row, xmin/xmax"
)


class ReviewService:
    def __init__(
        self, sm: async_sessionmaker[AsyncSession], bot: Bot, sink: DecisionSink, settings: ReviewSettings,
        ideas: IdeaAdder | None = None,
    ) -> None:  # fmt: skip
        self.sm, self.bot, self.sink, self.cfg = sm, bot, sink, settings
        self.ideas = ideas

    async def open(self, req: OpenRequest, now: datetime | None = None) -> Session:
        """Create the gate session and send its card. Safe to call again for the same `step_key`."""
        now = now or datetime.now(UTC)
        escalate = False
        async with transaction(self.sm) as s:
            row = await _by_step(s, req.step_key)
            if row is None:
                revisions = (
                    await s.scalar(
                        select(func.count()).select_from(Session).where(
                            Session.idea_ref == req.idea_ref, Session.gate == req.gate,
                            Session.status == "revision_requested",
                        )
                    )
                ) or 0  # fmt: skip
                escalate = revisions >= self.cfg.max_rounds
                row = Session(
                    step_key=req.step_key, idea_ref=req.idea_ref, gate=req.gate, round=revisions + 1,
                    status="escalated" if escalate else "pending", payload=req.payload,
                    chat_id=req.chat_id or min(self.cfg.owners), attempt_handle=req.handle,
                    deadline=now + timedelta(hours=self.cfg.deadline_h),
                )  # fmt: skip
                s.add(row)
                await s.flush()
                s.add(Event(session_id=row.id, kind="opened", text=f"round {row.round}"))
            if req.handle and row.attempt_handle != req.handle:
                row.attempt_handle = req.handle  # the live attempt is the one the platform will accept
        if escalate:
            await self._deliver(row.id, "escalated")
        elif row.message_id is None and row.status == "pending":
            await self._send(row.id)
        return await self.get(req.step_key)  # type: ignore[return-value]

    async def decision_for(self, step_key: str) -> Decision | None:
        """The decision of a finished gate (None while it is still open): lets a restarted step pick it up."""
        outcomes = {
            "approved": "approved", "revision_requested": "rejected", "escalated": "escalated",
            "expired": "expired", "cancelled": "cancelled",
        }  # fmt: skip
        row = await self.get(step_key)
        if row is None or row.status not in outcomes:
            return None
        return Decision(
            row.step_key, row.idea_ref, row.gate, outcomes[row.status], row.round, row.comment, row.attempt_handle
        )

    async def get(self, step_key: str) -> Session | None:
        async with transaction(self.sm) as s:
            return await _by_step(s, step_key)

    async def _send(self, session_id: int) -> None:
        async with transaction(self.sm) as s:
            row = await s.get(Session, session_id)
            assert row is not None  # noqa: S101
            prev = await s.scalar(
                select(Session.message_id).where(
                    Session.idea_ref == row.idea_ref, Session.gate == row.gate, Session.id < row.id,
                    Session.message_id.is_not(None),
                ).order_by(Session.id.desc()).limit(1)
            )  # fmt: skip
            card = build_card(row.gate, row.payload, row.round, row.id)
            chat = row.chat_id or 0
        try:
            mid = await self.bot.send_card(chat, card, reply_to=prev)  # revised cards reply to the previous one
        except TelegramError:
            return  # stays unsent; `resend_unsent` retries
        async with transaction(self.sm) as s:
            row = await s.get(Session, session_id)
            assert row is not None  # noqa: S101
            row.message_id = mid

    async def resend_unsent(self) -> int:
        async with transaction(self.sm) as s:
            ids = list(
                await s.scalars(select(Session.id).where(Session.status == "pending", Session.message_id.is_(None)))
            )
        for i in ids:
            await self._send(i)
        return len(ids)

    async def handle(self, u: Update) -> None:
        async with transaction(self.sm) as s:
            if await s.get(Seen, u.update_id) is not None:
                return
            s.add(Seen(update_id=u.update_id))
        if u.kind == "ignored":
            return
        if u.user_id not in self.cfg.owners and u.chat_id not in self.cfg.owners:
            if u.callback_id:
                await self.bot.answer_callback(u.callback_id, "Not allowed")
            return
        if u.kind == "callback":
            await self._on_tap(u)
        elif u.kind == "text" and u.text.strip().split(" ")[0].split("@")[0] == "/idea":
            await self._on_idea(u)
        elif u.kind == "text":
            await self._on_text(u)

    async def _on_tap(self, u: Update) -> None:
        parsed = parse_callback(u.text)
        assert u.callback_id is not None  # noqa: S101
        if parsed is None:
            await self.bot.answer_callback(u.callback_id, "Unknown action")
            return
        sid, action = parsed
        outcome: str | None = None
        async with transaction(self.sm) as s:
            row = await s.get(Session, sid)
            if row is None:
                answer = "Unknown card"
            elif row.status != "pending":
                answer = "Already handled"
            elif action == APPROVE:
                row.status, row.decided_by, row.decided_at = "approved", u.user_id, datetime.now(UTC)
                s.add(Event(session_id=sid, kind="approved"))
                answer, outcome = "Approved", "approved"
            else:
                row.status, row.decided_by = "awaiting_comment", u.user_id
                s.add(Event(session_id=sid, kind="rejected"))
                answer = "Send the comment: what to fix"
            chat, mid = (row.chat_id, row.message_id) if row else (None, None)
        await self.bot.answer_callback(u.callback_id, answer)
        if chat and mid and answer in {"Approved", "Send the comment: what to fix"}:
            await self._safe(self.bot.clear_buttons(chat, mid))
        if answer.startswith("Send") and chat:
            await self._safe(self.bot.send_text(chat, "What should be fixed? Reply with one message.", mid))
        if outcome:
            await self._deliver(sid, outcome)

    async def _on_idea(self, u: Update) -> None:
        """`/idea Series | Title | vision`: the idea goes to the backlog, queued; the conveyor takes it in turn."""
        rest = u.text.strip().partition(" ")[2]
        parts = [p.strip() for p in rest.split("|")]
        if self.ideas is None:
            await self._safe(self.bot.send_text(u.chat_id, "The idea backlog is not connected.", u.message_id))
            return
        if len(parts) < 2 or not parts[0] or not parts[1]:
            await self._safe(self.bot.send_text(u.chat_id, IDEA_HELP, u.message_id))
            return
        try:
            idea_id = await self.ideas(parts[0], parts[1], " | ".join(p for p in parts[2:] if p))
        except Exception as e:  # noqa: BLE001
            await self._safe(self.bot.send_text(u.chat_id, f"Could not add the idea: {type(e).__name__}", u.message_id))
            return
        await self._safe(self.bot.send_text(u.chat_id, f"💡 Queued idea #{idea_id}: {parts[1]}", u.message_id))

    async def _on_text(self, u: Update) -> None:
        async with transaction(self.sm) as s:
            row = (
                await s.scalars(
                    select(Session).where(Session.status == "awaiting_comment", Session.chat_id == u.chat_id)
                    .order_by(Session.id.desc()).limit(1)
                )
            ).first()  # fmt: skip
            if row is None:
                sid = None
            else:
                sid = row.id
                row.status, row.comment, row.decided_at = "revision_requested", u.text.strip(), datetime.now(UTC)
                s.add(Event(session_id=sid, kind="comment", text=u.text.strip()))
        if sid is None:
            await self._safe(self.bot.send_text(u.chat_id, "No card is waiting for a comment.", u.message_id))
            return
        await self._safe(self.bot.send_text(u.chat_id, "Got it, fixing now.", u.message_id))
        await self._deliver(sid, "rejected")

    async def _deliver(self, session_id: int, outcome: str) -> None:
        async with transaction(self.sm) as s:
            row = await s.get(Session, session_id)
            assert row is not None  # noqa: S101
            d = Decision(row.step_key, row.idea_ref, row.gate, outcome, row.round, row.comment, row.attempt_handle)
        try:
            await self.sink.decide(d)
        except Exception:  # noqa: BLE001 - redelivered by `redeliver`
            return
        async with transaction(self.sm) as s:
            row = await s.get(Session, session_id)
            assert row is not None  # noqa: S101
            row.delivered = True

    async def redeliver(self) -> int:
        """At-least-once: decisions the platform has not acknowledged are sent again."""
        outcomes = {"approved": "approved", "revision_requested": "rejected", "escalated": "escalated",
                    "expired": "expired", "cancelled": "cancelled"}  # fmt: skip
        async with transaction(self.sm) as s:
            rows = list(
                await s.execute(select(Session.id, Session.status).where(
                    Session.delivered.is_(False), Session.status.in_(list(outcomes))))
            )  # fmt: skip
        for sid, status in rows:
            await self._deliver(sid, outcomes[status])
        return len(rows)

    async def expire_due(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        async with transaction(self.sm) as s:
            rows = list(
                await s.scalars(
                    select(Session).where(Session.status.in_(["pending", "awaiting_comment"]), Session.deadline < now)
                )
            )
            for r in rows:
                r.status, r.decided_at = "expired", now
                s.add(Event(session_id=r.id, kind="expired"))
            ids = [r.id for r in rows]
        for i in ids:
            await self._deliver(i, "expired")
        return len(ids)

    async def cancel(self, step_key: str) -> bool:
        async with transaction(self.sm) as s:
            row = await _by_step(s, step_key)
            if row is None or row.status in {"approved", "revision_requested", "escalated", "expired", "cancelled"}:
                return False
            row.status = "cancelled"
            sid, chat, mid = row.id, row.chat_id, row.message_id
        if chat and mid:
            await self._safe(self.bot.clear_buttons(chat, mid))
        await self._deliver(sid, "cancelled")
        return True

    async def notify_published(self, idea_ref: str, text: str) -> bool:
        """ "What was published where": a reply to the approved post card."""
        async with transaction(self.sm) as s:
            row = (
                await s.scalars(
                    select(Session)
                    .where(Session.idea_ref == idea_ref, Session.gate == "post", Session.status == "approved")
                    .order_by(Session.id.desc()).limit(1)
                )
            ).first()  # fmt: skip
        if row is None or row.chat_id is None:
            return False
        await self.bot.send_text(row.chat_id, text, row.message_id)
        return True

    async def poll_once(self, offset: int) -> int:
        """One long-poll round; returns the next offset."""
        updates = await self.bot.get_updates(offset)
        for u in updates:
            await self.handle(u)
            offset = max(offset, u.update_id + 1)
        return offset

    @staticmethod
    async def _safe(coro: Any) -> None:
        try:
            await coro
        except TelegramError:
            pass


async def _by_step(s: AsyncSession, step_key: str) -> Session | None:
    return (await s.execute(select(Session).where(Session.step_key == step_key))).scalar_one_or_none()
