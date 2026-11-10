"""module_secrets + module_settings for bot token and non-secret config

Revision ID: 0004_module_secrets
Revises: 0003_telegram_updates
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_module_secrets"
down_revision: str | None = "0003_telegram_updates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE module_secrets (
          key text PRIMARY KEY,
          value text NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE module_secrets IS
          'Module-owned secrets (bot tokens, S3 keys). Never expose via API or logs.';
        CREATE TABLE module_settings (
          key text PRIMARY KEY,
          value jsonb NOT NULL DEFAULT '{}'::jsonb,
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE module_settings IS
          'Non-secret module config (admin/chat ids, S3 endpoints, modes).';
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS module_settings;")
    op.execute("DROP TABLE IF EXISTS module_secrets;")
