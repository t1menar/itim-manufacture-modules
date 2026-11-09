"""D23: platform accounts and publish intents owned by module-publish."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_accounts_intents"
down_revision = "0002_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text()),
        sa.Column("external_id", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("channel_id", "platform", "handle", name="uq_platform_accounts_channel_platform_handle"),
    )
    op.create_table(
        "publish_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("platform_accounts.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("content_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("external_post_id", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_error", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("variant_id", "platform_account_id", "generation", name="uq_publish_intents_variant_account_gen"),
    )
    # MVP seed: iTim Instagram (opaque id stable for tests / local)
    op.execute(
        """
        INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled)
        VALUES ('0193a000-0000-7000-8000-000000000001', 'itim', 'instagram', '@itim', true)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("publish_intents")
    op.drop_table("platform_accounts")
