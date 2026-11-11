"""attempt handle of the waiting platform attempt

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("attempt_handle", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "attempt_handle")
