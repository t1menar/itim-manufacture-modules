"""phase1: amqp inbox + bot_state placeholder

Revision ID: 0001_phase1
Revises:
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_phase1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE amqp_inbox (
          message_id text PRIMARY KEY,
          message_type text NOT NULL,
          received_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX amqp_inbox_received_idx ON amqp_inbox (received_at);

        CREATE TABLE bot_state (
          key text PRIMARY KEY,
          value jsonb NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bot_state, amqp_inbox;")
