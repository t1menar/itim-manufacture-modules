"""credential refs are CAPITAL_SNAKE_CASE

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint("ck_credentials_ref", "credentials", "ref ~ '^[A-Z][A-Z0-9_]{1,63}$'")


def downgrade() -> None:
    op.drop_constraint("ck_credentials_ref", "credentials", type_="check")
