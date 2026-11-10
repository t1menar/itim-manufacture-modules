"""runs.mode accepts 'republish' (core sends it for an admin republish)

Revision ID: 0006_runs_mode_republish
Revises: 0005_publish_ledger
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_runs_mode_republish"
down_revision: str | None = "0005_publish_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_mode_check")
    op.execute("ALTER TABLE runs ADD CONSTRAINT runs_mode_check CHECK (mode IN ('create','revise','republish'))")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_mode_check")
    op.execute("ALTER TABLE runs ADD CONSTRAINT runs_mode_check CHECK (mode IN ('create','revise'))")
