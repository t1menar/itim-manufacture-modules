"""credentials stored in the module database (local deployment)

Expand-only: one new table. Values are plain text: the module runs on the owner's machine.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = pg.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("ref", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("updated_by", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("credentials")
