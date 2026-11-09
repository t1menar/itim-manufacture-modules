"""module_secrets/settings + platform_accounts.access_token

Revision ID: 0004_module_secrets
Revises: 0003_accounts_intents
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_module_secrets"
down_revision: str | None = "0003_accounts_intents"
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
          'Module-owned secrets (S3 keys, shared defaults). Never expose via API or logs.';
        CREATE TABLE module_settings (
          key text PRIMARY KEY,
          value jsonb NOT NULL DEFAULT '{}'::jsonb,
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE platform_accounts
          ADD COLUMN IF NOT EXISTS access_token text;
        COMMENT ON COLUMN platform_accounts.access_token IS
          'Instagram Graph long-lived user token; never return via API.';
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE platform_accounts DROP COLUMN IF EXISTS access_token;")
    op.execute("DROP TABLE IF EXISTS module_settings;")
    op.execute("DROP TABLE IF EXISTS module_secrets;")
