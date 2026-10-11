"""shared suggestion tracker (Phase A)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28

Adds trade_suggestions + the append-only trade_suggestion_events log. Purely
additive: no existing table is altered. The dormant momentum_* models are
intentionally NOT migrated here.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scanner_type", sa.String(16), nullable=False),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("underlying_symbol", sa.String(64)),
        sa.Column("instrument_type", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("setup_type", sa.String(64), nullable=False),
        sa.Column("coexistence_group", sa.String(32), nullable=False),
        sa.Column("open_dedup_key", sa.String(256)),
        sa.Column("scanner_run_id", sa.Integer),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_session_date", sa.Date, nullable=False),
        sa.Column("generation_market_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("generation_price_source", sa.String(32), nullable=False),
        sa.Column("generation_price_zone_position", sa.String(16), nullable=False),
        sa.Column("market_status", sa.String(32), nullable=False),
        sa.Column("data_quality", sa.String(32), nullable=False),
        sa.Column("entry_rule", sa.String(48), nullable=False),
        sa.Column("entry_low", sa.Numeric(18, 4), nullable=False),
        sa.Column("entry_high", sa.Numeric(18, 4), nullable=False),
        sa.Column("reference_entry_price", sa.Numeric(18, 4)),
        sa.Column("target_1", sa.Numeric(18, 4), nullable=False),
        sa.Column("target_2", sa.Numeric(18, 4)),
        sa.Column("stop_loss", sa.Numeric(18, 4), nullable=False),
        sa.Column("invalidation_price", sa.Numeric(18, 4)),
        sa.Column("level_quality", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("level_notes", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("suggested_holding_period", sa.String(64)),
        sa.Column("entry_window_sessions", sa.Integer),
        sa.Column("max_holding_sessions", sa.Integer),
        sa.Column("entry_deadline_session_date", sa.Date),
        sa.Column("holding_deadline_session_date", sa.Date),
        sa.Column("session_calendar_verified", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("score", sa.Numeric(8, 3)),
        sa.Column("confidence", sa.Numeric(8, 3)),
        sa.Column("option_symbol", sa.String(64)),
        sa.Column("option_strike", sa.Numeric(18, 4)),
        sa.Column("option_type", sa.String(4)),
        sa.Column("option_expiry", sa.Date),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("entry_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("entry_triggered_price", sa.Numeric(18, 4)),
        sa.Column("target_1_hit_at", sa.DateTime(timezone=True)),
        sa.Column("target_1_hit_price", sa.Numeric(18, 4)),
        sa.Column("target_2_hit_at", sa.DateTime(timezone=True)),
        sa.Column("target_2_hit_price", sa.Numeric(18, 4)),
        sa.Column("stop_hit_at", sa.DateTime(timezone=True)),
        sa.Column("stop_hit_price", sa.Numeric(18, 4)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("close_price", sa.Numeric(18, 4)),
        sa.Column("max_favorable_price", sa.Numeric(18, 4)),
        sa.Column("max_adverse_price", sa.Numeric(18, 4)),
        sa.Column("max_favorable_excursion", sa.Numeric(10, 4)),
        sa.Column("max_adverse_excursion", sa.Numeric(10, 4)),
        sa.Column("realized_or_marked_return_pct", sa.Numeric(10, 4)),
        sa.Column("return_is_realized", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("post_target_1_adverse_price", sa.Numeric(18, 4)),
        sa.Column("breakeven_revisited_after_target_1_at", sa.DateTime(timezone=True)),
        sa.Column("ambiguous_bar", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("failure_reason", sa.String(512)),
        sa.Column("last_observed_price", sa.Numeric(18, 4)),
        sa.Column("last_observed_at", sa.DateTime(timezone=True)),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_snapshot", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("research_metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("open_dedup_key", name="uq_trade_suggestions_open_dedup_key"),
    )
    op.create_index("ix_trade_suggestions_scanner_type", "trade_suggestions", ["scanner_type"])
    op.create_index("ix_trade_suggestions_symbol", "trade_suggestions", ["symbol"])
    op.create_index("ix_trade_suggestions_scanner_run_id", "trade_suggestions", ["scanner_run_id"])
    op.create_index("ix_trade_suggestions_generated_at", "trade_suggestions", ["generated_at"])
    op.create_index("ix_trade_suggestions_generation_session_date", "trade_suggestions", ["generation_session_date"])
    op.create_index("ix_trade_suggestions_status", "trade_suggestions", ["status"])
    op.create_index("ix_trade_suggestions_outcome", "trade_suggestions", ["outcome"])

    op.create_table(
        "trade_suggestion_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "suggestion_id", sa.Integer,
            sa.ForeignKey("trade_suggestions.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32)),
        sa.Column("threshold_price", sa.Numeric(18, 4)),
        sa.Column("observed_market_price", sa.Numeric(18, 4)),
        sa.Column("observed_price_basis", sa.String(32)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("data_source", sa.String(32)),
        sa.Column("ambiguous_bar", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("detail", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("suggestion_id", "sequence", name="uq_trade_suggestion_event_sequence"),
    )
    op.create_index("ix_trade_suggestion_events_suggestion_id", "trade_suggestion_events", ["suggestion_id"])
    op.create_index("ix_trade_suggestion_events_event_type", "trade_suggestion_events", ["event_type"])

    # Database-level append-only guarantee (the ORM guard only covers code
    # that goes through SQLAlchemy's unit of work).
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION trade_suggestion_events_append_only() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'trade_suggestion_events is append-only (% refused)', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_trade_suggestion_events_append_only
            BEFORE UPDATE OR DELETE ON trade_suggestion_events
            FOR EACH ROW EXECUTE FUNCTION trade_suggestion_events_append_only();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_trade_suggestion_events_append_only ON trade_suggestion_events")
        op.execute("DROP FUNCTION IF EXISTS trade_suggestion_events_append_only()")
    op.drop_table("trade_suggestion_events")
    op.drop_table("trade_suggestions")
