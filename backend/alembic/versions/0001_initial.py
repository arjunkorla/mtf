"""initial schema (section 22)

Revision ID: 0001
Revises:
Create Date: 2026-09-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
        sa.Column("exchange", sa.String(8), nullable=False, server_default="NSE"),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(128)),
        sa.Column("industry", sa.String(128)),
        sa.Column("is_fno", sa.Boolean, server_default=sa.false()),
        sa.Column("is_mtf_eligible", sa.Boolean, server_default=sa.false()),
        sa.Column("is_liquid", sa.Boolean, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("isin", sa.String(32)),
        sa.Column("lot_size", sa.Integer),
        sa.Column("face_value", sa.Numeric(12, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stocks_symbol", "stocks", ["symbol"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("open", sa.Numeric(14, 4), nullable=False),
        sa.Column("high", sa.Numeric(14, 4), nullable=False),
        sa.Column("low", sa.Numeric(14, 4), nullable=False),
        sa.Column("close", sa.Numeric(14, 4), nullable=False),
        sa.Column("volume", sa.Integer, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="fyers"),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stock_id", "trade_date", name="uq_price_history_stock_date"),
    )
    op.create_index("ix_price_history_stock_id", "price_history", ["stock_id"])
    op.create_index("ix_price_history_trade_date", "price_history", ["trade_date"])

    op.create_table(
        "technical_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("ema_20", sa.Numeric(14, 4)),
        sa.Column("ema_50", sa.Numeric(14, 4)),
        sa.Column("ema_200", sa.Numeric(14, 4)),
        sa.Column("rsi_14", sa.Numeric(6, 2)),
        sa.Column("atr_14", sa.Numeric(14, 4)),
        sa.Column("adx_14", sa.Numeric(6, 2)),
        sa.Column("vwap", sa.Numeric(14, 4)),
        sa.Column("recent_high_20d", sa.Numeric(14, 4)),
        sa.Column("recent_low_20d", sa.Numeric(14, 4)),
        sa.Column("support_level", sa.Numeric(14, 4)),
        sa.Column("resistance_level", sa.Numeric(14, 4)),
        sa.Column("trend_structure", sa.String(32)),
        sa.Column("breakout_status", sa.String(32)),
        sa.Column("pullback_status", sa.String(32)),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "volume_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("avg_volume_20d", sa.Numeric(18, 2)),
        sa.Column("volume_ratio", sa.Numeric(8, 3)),
        sa.Column("relative_volume", sa.Numeric(8, 3)),
        sa.Column("high_volume_up_days_20d", sa.Integer),
        sa.Column("high_volume_down_days_20d", sa.Integer),
        sa.Column("consolidation_volume_avg", sa.Numeric(18, 2)),
        sa.Column("breakout_volume", sa.Numeric(18, 2)),
        sa.Column("accumulation_score", sa.Numeric(6, 2)),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "fno_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("futures_price_change_pct", sa.Numeric(8, 3)),
        sa.Column("futures_oi_change_pct", sa.Numeric(8, 3)),
        sa.Column("futures_volume", sa.Numeric(18, 2)),
        sa.Column("call_oi_total", sa.Numeric(18, 2)),
        sa.Column("put_oi_total", sa.Numeric(18, 2)),
        sa.Column("put_call_oi_ratio", sa.Numeric(8, 3)),
        sa.Column("max_oi_strike_call", sa.Numeric(14, 4)),
        sa.Column("max_oi_strike_put", sa.Numeric(14, 4)),
        sa.Column("positioning_proxy", sa.String(32)),
        sa.Column("is_available", sa.Boolean, server_default=sa.false()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "fundamentals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("revenue_growth_yoy_pct", sa.Numeric(8, 3)),
        sa.Column("profit_growth_yoy_pct", sa.Numeric(8, 3)),
        sa.Column("eps", sa.Numeric(14, 4)),
        sa.Column("net_margin_pct", sa.Numeric(8, 3)),
        sa.Column("debt_to_equity", sa.Numeric(8, 3)),
        sa.Column("roe_pct", sa.Numeric(8, 3)),
        sa.Column("roce_pct", sa.Numeric(8, 3)),
        sa.Column("pe_ratio", sa.Numeric(10, 3)),
        sa.Column("pb_ratio", sa.Numeric(10, 3)),
        sa.Column("is_available", sa.Boolean, server_default=sa.false()),
        sa.Column("fiscal_period", sa.String(32)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "news",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("headline", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("category", sa.String(64)),
        sa.Column("sentiment", sa.String(16), nullable=False, server_default="UNKNOWN"),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(1024)),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_stock_id", "news", ["stock_id"])

    op.create_table(
        "sector_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sector_name", sa.String(128), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("sector_index_symbol", sa.String(32)),
        sa.Column("relative_strength_vs_nifty", sa.Numeric(8, 3)),
        sa.Column("momentum_5d_pct", sa.Numeric(8, 3)),
        sa.Column("momentum_20d_pct", sa.Numeric(8, 3)),
        sa.Column("sector_strength_label", sa.String(32)),
        sa.Column("market_regime", sa.String(32)),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sector_metrics_sector_name", "sector_metrics", ["sector_name"])

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("total_score", sa.Numeric(6, 2)),
        sa.Column("score_components", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("unavailable_components", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("institutional_footprint_score", sa.Numeric(6, 2)),
        sa.Column("institutional_footprint_level", sa.String(32), nullable=False, server_default="INSUFFICIENT_DATA"),
        sa.Column("institutional_footprint_evidence", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("setup_type", sa.String(64)),
        sa.Column("setup_strength", sa.String(16)),
        sa.Column("supporting_evidence", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("conflicting_evidence", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("invalidation_condition", sa.String(512)),
        sa.Column("signal_quality", sa.String(16)),
        sa.Column("data_quality_score", sa.Numeric(6, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signals_stock_id", "signals", ["stock_id"])
    op.create_index("ix_signals_as_of_date", "signals", ["as_of_date"])

    op.create_table(
        "scanner_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("available_capital", sa.Numeric(18, 2), nullable=False),
        sa.Column("risk_percent", sa.Numeric(6, 3), nullable=False),
        sa.Column("max_positions", sa.Integer, nullable=False),
        sa.Column("holding_period", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("stocks_analyzed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("stocks_rejected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("stocks_selected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("execution_ms", sa.Integer),
        sa.Column("error_message", sa.String(1024)),
        sa.Column("rejection_summary", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "scanner_results",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("scanner_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("score", sa.Numeric(6, 2), nullable=False),
        sa.Column("signal_quality", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scanner_results_run_id", "scanner_results", ["run_id"])
    op.create_index("ix_scanner_results_stock_id", "scanner_results", ["stock_id"])
    op.create_index("ix_scanner_results_symbol", "scanner_results", ["symbol"])


def downgrade() -> None:
    op.drop_table("scanner_results")
    op.drop_table("scanner_runs")
    op.drop_table("signals")
    op.drop_table("sector_metrics")
    op.drop_table("news")
    op.drop_table("fundamentals")
    op.drop_table("fno_metrics")
    op.drop_table("volume_metrics")
    op.drop_table("technical_metrics")
    op.drop_table("price_history")
    op.drop_table("stocks")
