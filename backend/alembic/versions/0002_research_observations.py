"""research observation layer (Phase 6)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_market_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timestamp_ist", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_label", sa.String(16), nullable=False),
        sa.Column("nifty_regime", sa.String(32), nullable=False),
        sa.Column("india_vix", sa.Numeric(8, 3)),
        sa.Column("vix_regime", sa.String(32), nullable=False),
        sa.Column("global_risk_sentiment", sa.String(32), nullable=False),
        sa.Column("global_macro_payload", sa.JSON, nullable=False),
        sa.Column("source_provenance", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_date", "slot_label", name="uq_research_market_snapshot_session_slot"),
    )
    op.create_index("ix_research_market_snapshots_session_date", "research_market_snapshots", ["session_date"])
    op.create_index("ix_research_market_snapshots_timestamp_utc", "research_market_snapshots", ["timestamp_utc"])

    op.create_table(
        "research_observations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timestamp_ist", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column(
            "market_snapshot_id", sa.Integer,
            sa.ForeignKey("research_market_snapshots.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("observed_price", sa.Numeric(14, 4)),
        sa.Column("mtf_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("mtf_rank", sa.Integer),
        sa.Column("research_confirmation_score", sa.Numeric(6, 2)),
        sa.Column("research_rank", sa.Integer),
        sa.Column("research_status", sa.String(32), nullable=False),
        sa.Column("technical_state", sa.String(64)),
        sa.Column("stock_return_5d", sa.Numeric(8, 3)),
        sa.Column("stock_return_20d", sa.Numeric(8, 3)),
        sa.Column("sector", sa.String(128)),
        sa.Column("sector_state", sa.String(32)),
        sa.Column("sector_return_5d", sa.Numeric(8, 3)),
        sa.Column("sector_return_20d", sa.Numeric(8, 3)),
        sa.Column("stock_vs_sector_5d", sa.Numeric(8, 3)),
        sa.Column("stock_vs_sector_20d", sa.Numeric(8, 3)),
        sa.Column("stock_vs_nifty_5d", sa.Numeric(8, 3)),
        sa.Column("stock_vs_nifty_20d", sa.Numeric(8, 3)),
        sa.Column("sector_participation", sa.String(32), nullable=False),
        sa.Column("sector_participation_evidence", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("volume_state", sa.String(64)),
        sa.Column("delivery_state", sa.String(64)),
        sa.Column("institutional_proxy", sa.String(32)),
        sa.Column("futures_state", sa.String(32)),
        sa.Column("futures_oi_context", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("options_context", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("live_confirmation_status", sa.String(32)),
        sa.Column("live_confirmation_score", sa.Numeric(6, 2)),
        sa.Column("market_regime", sa.String(32)),
        sa.Column("news_context", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("corporate_event_context", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("supporting_signals", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("conflicting_signals", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("risk_signals", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("missing_data", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("core_data_quality", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("research_data_coverage", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("live_confirmation_coverage", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("entry_zone", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("invalidation", sa.Numeric(14, 4)),
        sa.Column("source_provenance", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("research_minus_mtf", sa.Numeric(6, 2)),
        sa.Column("research_rank_minus_mtf_rank", sa.Integer),
        sa.Column("divergence_classification", sa.String(32), nullable=False),
        sa.Column("outcome_status", sa.String(32), nullable=False, server_default="OUTCOME_PENDING"),
        sa.Column("next_1d_return", sa.Numeric(8, 3)),
        sa.Column("next_3d_return", sa.Numeric(8, 3)),
        sa.Column("next_5d_return", sa.Numeric(8, 3)),
        sa.Column("next_10d_return", sa.Numeric(8, 3)),
        sa.Column("next_20d_return", sa.Numeric(8, 3)),
        sa.Column("maximum_favorable_excursion", sa.Numeric(8, 3)),
        sa.Column("maximum_adverse_excursion", sa.Numeric(8, 3)),
        sa.Column("invalidation_hit", sa.Boolean),
        sa.Column("entry_zone_reached", sa.Boolean),
        sa.Column("outcome_computed_at", sa.DateTime(timezone=True)),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("market_snapshot_id", "symbol", name="uq_research_observation_snapshot_symbol"),
    )
    op.create_index("ix_research_observations_session_date", "research_observations", ["session_date"])
    op.create_index("ix_research_observations_timestamp_utc", "research_observations", ["timestamp_utc"])
    op.create_index("ix_research_observations_symbol", "research_observations", ["symbol"])
    op.create_index("ix_research_observations_market_snapshot_id", "research_observations", ["market_snapshot_id"])


def downgrade() -> None:
    op.drop_table("research_observations")
    op.drop_table("research_market_snapshots")
