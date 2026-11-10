"""the core's fence of the job: sent back as X-Fence on every callback

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("fence", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("runs", "fence")
