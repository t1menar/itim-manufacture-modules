"""runtime prompts in the module database: immutable versions, activation, audit (D16 / C40)

Expand-only: three new tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = pg.TIMESTAMP(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("claude_md", sa.Text, nullable=False),
        sa.Column("task_md", sa.Text, nullable=False),
        sa.Column("placeholders", pg.JSONB, nullable=False),
        sa.Column("meta", pg.JSONB, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_by", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("step", "version", name="uq_prompt_versions_step_version"),
    )
    op.create_table(
        "prompt_active",
        sa.Column("step", sa.Text, primary_key=True),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("updated_by", sa.Text),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    op.create_table(
        "prompt_audit",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("at", TS, nullable=False, server_default=NOW),
        sa.Column("actor", sa.Text),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("previous_version", sa.Text),
        sa.Column("note", sa.Text),
    )


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only (03 section 7)")
