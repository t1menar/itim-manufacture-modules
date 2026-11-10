"""publish_ledger: one row per (intent, account) so a retry never posts the same reel twice

Revision ID: 0005_publish_ledger
Revises: 0004_module_secrets
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_publish_ledger"
down_revision: str | None = "0004_module_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE publish_ledger (
          intent_key text NOT NULL,
          account_id text NOT NULL,
          status text NOT NULL CHECK (status IN ('claimed','publishing','published','unknown','failed')),
          run_id uuid NOT NULL,
          fence integer NOT NULL,
          container_id text,
          caption text,
          external_post_id text,
          url text,
          published_at timestamptz,
          claimed_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (intent_key, account_id)
        );
        COMMENT ON TABLE publish_ledger IS
          'Publish attempts per intent and account; publishing/published/unknown rows are never re-posted.';
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE publish_ledger")
