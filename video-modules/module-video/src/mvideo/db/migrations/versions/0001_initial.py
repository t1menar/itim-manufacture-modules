"""initial schema of database video

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = pg.TIMESTAMP(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("production_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False, server_default="en"),
        sa.Column("variant_id", pg.UUID(as_uuid=True)),
        sa.Column("status", sa.Text, nullable=False, server_default="accepted"),
        sa.Column("current_step", sa.Text),
        sa.Column("percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("settings_version", sa.Integer, nullable=False),
        sa.Column("settings", pg.JSONB, nullable=False),
        sa.Column("input", pg.JSONB, nullable=False),
        sa.Column("deadline", TS, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("result", pg.JSONB),
        sa.Column("error", pg.JSONB),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("lease_owner", sa.Text),
        sa.Column("lease_until", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.UniqueConstraint("job_id", name="uq_runs_job_id"),
        sa.CheckConstraint(
            "status in ('accepted', 'running', 'succeeded', 'failed', 'cancelling', 'cancelled')",
            name="ck_runs_status",
        ),
        sa.CheckConstraint("mode in ('create', 'revise')", name="ck_runs_mode"),
    )
    op.create_index("ix_runs_production_created", "runs", ["production_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_runs_active_status",
        "runs",
        ["status"],
        postgresql_where=sa.text("status in ('accepted', 'running', 'cancelling')"),
    )

    op.create_table(
        "steps",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id", pg.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("try", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("input_hash", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("outputs", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reused_from", pg.UUID(as_uuid=True), sa.ForeignKey("steps.id", ondelete="SET NULL")),
        sa.Column("error", pg.JSONB),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("num_turns", sa.Integer, nullable=False, server_default="0"),
        sa.Column("session_id", sa.Text),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("duration_s", sa.Float),
        sa.UniqueConstraint("run_id", "name", "try", name="uq_steps_run_name_try"),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'reused', 'blocked', 'failed', 'skipped')",
            name="ck_steps_status",
        ),
    )
    op.create_index("ix_steps_input_hash", "steps", ["input_hash"])

    op.create_table(
        "checks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", pg.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("step_id", pg.UUID(as_uuid=True), sa.ForeignKey("steps.id", ondelete="CASCADE")),
        sa.Column("check", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("value", pg.JSONB),
        sa.Column("limit", pg.JSONB),
        sa.Column("details", pg.JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("status in ('pass', 'warn', 'fail')", name="ck_checks_status"),
    )
    op.create_index("ix_checks_run_id", "checks", ["run_id"])

    op.create_table(
        "sandbox_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "step_id", pg.UUID(as_uuid=True), sa.ForeignKey("steps.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("image", sa.Text, nullable=False),
        sa.Column("digest", sa.Text),
        sa.Column("version_string", sa.Text),
        sa.Column("container_id", sa.Text),
        sa.Column("limits", pg.JSONB),
        sa.Column("exit", sa.Text),
        sa.Column("log_ref", sa.Text),
        sa.Column("started_at", TS, nullable=False, server_default=NOW),
        sa.Column("finished_at", TS),
        sa.CheckConstraint("purpose in ('capture', 'scratch')", name="ck_sandbox_runs_purpose"),
    )
    op.create_index("ix_sandbox_runs_step_id", "sandbox_runs", ["step_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "step_id", pg.UUID(as_uuid=True), sa.ForeignKey("steps.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("container_id", sa.Text),
        sa.Column("image_digest", sa.Text),
        sa.Column("sdk_version", sa.Text),
        sa.Column("cli_version", sa.Text),
        sa.Column("session_id", sa.Text),
        sa.Column("stop_reason", sa.Text),
        sa.Column("turns", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("usage", pg.JSONB),
        sa.Column("transcript_ref", sa.Text),
        sa.Column("egress_denied", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", TS, nullable=False, server_default=NOW),
        sa.Column("finished_at", TS),
    )
    op.create_index("ix_agent_runs_step_id", "agent_runs", ["step_id"])

    op.create_table(
        "source_cache",
        sa.Column("repo_url", sa.Text, primary_key=True),
        sa.Column("commit", sa.String(40), primary_key=True),
        sa.Column("volume", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("last_used_at", TS, nullable=False, server_default=NOW),
    )

    op.create_table(
        "usage_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True)),
        sa.Column("step", sa.Text),
        sa.Column("at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("kind in ('job', 'agent_run')", name="ck_usage_log_kind"),
    )
    op.create_index("ix_usage_log_kind_at", "usage_log", ["kind", "at"])

    op.create_table(
        "golden_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", sa.Text, nullable=False),
        sa.Column("overrides", pg.JSONB),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("report", pg.JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("finished_at", TS),
    )


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only (03 section 7)")
