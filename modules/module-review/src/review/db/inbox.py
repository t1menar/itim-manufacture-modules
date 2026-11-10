"""AMQP inbox deduplication (message_id primary key)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def try_claim(session: AsyncSession, message_id: str, message_type: str) -> bool:
    """Insert inbox row; return True if this consumer should process the message."""
    result = await session.execute(
        text(
            """
            INSERT INTO amqp_inbox (message_id, message_type)
            VALUES (:id, :type)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
            """
        ),
        {"id": message_id, "type": message_type},
    )
    return result.first() is not None
