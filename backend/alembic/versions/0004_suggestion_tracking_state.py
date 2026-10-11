"""suggestion tracker bookkeeping (Phase B)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29

Adds three MUTABLE tracker columns to trade_suggestions. Purely additive:
no existing column, constraint, trigger or row value is changed, and the
generation-time evidence/levels are untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trade_suggestions", sa.Column("reconciled_through", sa.DateTime(timezone=True)))
    op.add_column(
        "trade_suggestions",
        sa.Column("tracking_status", sa.String(32), nullable=False, server_default="NOT_TRACKED"),
    )
    op.add_column("trade_suggestions", sa.Column("tracking_status_reason", sa.String(256)))
    op.create_index("ix_trade_suggestions_tracking_status", "trade_suggestions", ["tracking_status"])


def downgrade() -> None:
    op.drop_index("ix_trade_suggestions_tracking_status", table_name="trade_suggestions")
    op.drop_column("trade_suggestions", "tracking_status_reason")
    op.drop_column("trade_suggestions", "tracking_status")
    op.drop_column("trade_suggestions", "reconciled_through")
