"""ideas and topics owned by module-video, idea outbox and AMQP inbox (D21)

Expand-only: new tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = pg.TIMESTAMP(timezone=True)
NOW = sa.text("now()")
STATUSES = (
    "draft", "ready", "queued", "dispatched", "in_production", "done", "failed", "cancelled", "archived",
)  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("default_tags", pg.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("default_platforms", pg.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("rev", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("code", name="uq_topics_code"),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,63}$'", name="ck_topics_code"),
    )
    op.create_table(
        "ideas",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("topic_id", sa.BigInteger, sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("hook", sa.Text),
        sa.Column("audience", sa.Text),
        sa.Column("tags", pg.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("references", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("constraints", pg.JSONB),
        sa.Column("language", sa.Text, nullable=False, server_default="en"),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.Text),
        sa.Column("author", sa.Text),
        sa.Column("pipeline_id", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("rev", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("ready_at", TS),
        sa.Column("queued_at", TS),
        sa.Column("dispatched_at", TS),
        sa.Column("last_message_id", pg.UUID(as_uuid=True)),
        sa.Column("failure", pg.JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status in (" + ", ".join(repr(x) for x in STATUSES) + ")", name="ck_ideas_status"
        ),
    )
    op.create_index(
        "ix_ideas_queue", "ideas", [sa.text("priority DESC"), "queued_at", "id"],
        postgresql_where=sa.text("status = 'queued'"),
    )  # fmt: skip
    op.create_table(
        "idea_revisions",
        sa.Column("idea_id", sa.BigInteger, sa.ForeignKey("ideas.id"), primary_key=True),
        sa.Column("rev", sa.Integer, primary_key=True),
        sa.Column("document", pg.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
    )
    op.create_table(
        "idea_outbox",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("idea_id", sa.BigInteger, nullable=False),
        sa.Column("rev", sa.Integer, nullable=False),
        sa.Column("routing_key", sa.Text, nullable=False),
        sa.Column("envelope", pg.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("published_at", TS),
        sa.UniqueConstraint("message_id", name="uq_idea_outbox_message_id"),
        sa.UniqueConstraint("idea_id", "rev", "routing_key", name="uq_idea_outbox_idea_rev_key"),
    )
    op.create_index(
        "ix_idea_outbox_pending",
        "idea_outbox",
        ["created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "amqp_inbox",
        sa.Column("message_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("received_at", TS, nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only (03 section 7)")
