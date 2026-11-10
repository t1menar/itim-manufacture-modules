"""review runs, sessions, cards, pending reject

Revision ID: 0002_review_sessions
Revises: 0001_phase1
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_review_sessions"
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
          round integer NOT NULL DEFAULT 1,
          status text NOT NULL DEFAULT 'accepted'
            CHECK (status IN ('accepted','running','awaiting_decision','awaiting_reason',
                              'succeeded','failed','cancelling','cancelled')),
          percent integer NOT NULL DEFAULT 0,
          step text,
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
          WHERE status IN ('accepted','running','awaiting_decision','awaiting_reason','cancelling');

        CREATE TABLE review_cards (
          id uuid PRIMARY KEY,
          run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          variant_id uuid NOT NULL,
          version integer NOT NULL,
          chat_id bigint NOT NULL,
          message_id integer NOT NULL,
          stale boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (variant_id, version)
        );
        CREATE INDEX review_cards_variant_idx ON review_cards (variant_id, version DESC);

        CREATE TABLE pending_reject (
          run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
          chat_id bigint NOT NULL,
          admin_user_id bigint NOT NULL,
          card_message_id integer,
          asked_message_id integer,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_reject, review_cards, runs;")
