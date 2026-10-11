"""MTF daily evidence collection (Phase D)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29

1. mtf_collection_runs: one row per scheduled collection stage (SCAN after
   the close on completed daily candles, GENERATE at the next session's
   fixed slot). `dedup_key` is UNIQUE and NULL only for operator-forced
   runs, so a restart/retry can never run the same stage twice for the
   same session.
2. Three MUTABLE, tracker-owned columns on trade_suggestions recording WHEN
   the favorable/adverse extremes were first observed and the adverse
   extreme before target 1. Purely additive; existing rows keep NULL
   (never back-filled / invented).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mtf_collection_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("dry_run", sa.Boolean, nullable=False),
        sa.Column("forced", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("dedup_key", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(512)),
        sa.Column("scanner_run_id", sa.Integer),
        sa.Column("scan_collection_run_id", sa.Integer),
        sa.Column("candidates", sa.Integer),
        sa.Column("eligible", sa.Integer),
        sa.Column("rejected", sa.Integer),
        sa.Column("persisted", sa.Integer),
        sa.Column("summary", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("dedup_key", name="uq_mtf_collection_runs_dedup_key"),
    )
    op.create_index("ix_mtf_collection_runs_session_date", "mtf_collection_runs", ["session_date"])
    op.create_index("ix_mtf_collection_runs_stage", "mtf_collection_runs", ["stage"])

    op.add_column("trade_suggestions", sa.Column("max_favorable_at", sa.DateTime(timezone=True)))
    op.add_column("trade_suggestions", sa.Column("max_adverse_at", sa.DateTime(timezone=True)))
    op.add_column("trade_suggestions", sa.Column("max_adverse_price_before_target_1", sa.Numeric(18, 4)))


def downgrade() -> None:
    op.drop_column("trade_suggestions", "max_adverse_price_before_target_1")
    op.drop_column("trade_suggestions", "max_adverse_at")
    op.drop_column("trade_suggestions", "max_favorable_at")
    op.drop_index("ix_mtf_collection_runs_stage", table_name="mtf_collection_runs")
    op.drop_index("ix_mtf_collection_runs_session_date", table_name="mtf_collection_runs")
    op.drop_table("mtf_collection_runs")
