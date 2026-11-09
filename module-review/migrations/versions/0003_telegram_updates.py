"""telegram update_id idempotency table

Revision ID: 0003_telegram_updates
Revises: 0002_review_sessions
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_telegram_updates"
down_revision: str | None = "0002_review_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE telegram_updates_seen (
          update_id bigint PRIMARY KEY,
          processed_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telegram_updates_seen;")
