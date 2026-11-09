"""runs table with lease for job intake

Revision ID: 0002_runs
Revises: 0001_phase1
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_runs"
down_revision: str | None = "0001_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE runs (
          id uuid PRIMARY KEY,
          job_id uuid NOT NULL UNIQUE,
          attempt integer NOT NULL,
          fence integer NOT NULL DEFAULT 1,
          production_id uuid NOT NULL,
          variant_id uuid,
          mode text NOT NULL CHECK (mode IN ('create','revise')),
          status text NOT NULL DEFAULT 'accepted'
            CHECK (status IN ('accepted','running','succeeded','failed','cancelling','cancelled')),
          percent integer NOT NULL DEFAULT 0,
          step text,
          settings_version integer NOT NULL DEFAULT 1,
          settings jsonb NOT NULL DEFAULT '{}',
          input jsonb NOT NULL,
          deadline timestamptz NOT NULL,
          callback_base_url text,
          result jsonb,
          error jsonb,
          cancel_requested boolean NOT NULL DEFAULT false,
          lease_owner text,
          lease_until timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          started_at timestamptz,
          finished_at timestamptz
        );
        CREATE INDEX runs_active_idx ON runs (status)
          WHERE status IN ('accepted','running','cancelling');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runs;")
