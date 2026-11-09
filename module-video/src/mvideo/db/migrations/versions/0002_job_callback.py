"""store the callback address, credential references and trace context of a job

Expand-only (nullable columns): the job request carries them and the runner needs them after
a restart to send callbacks (05 section 8).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("callback_base_url", sa.Text))
    op.add_column("runs", sa.Column("credential_refs", pg.JSONB))
    op.add_column("runs", sa.Column("traceparent", sa.Text))


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only (03 section 7)")
