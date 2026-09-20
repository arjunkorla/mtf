from app.data.normalization import (
    normalize_depth,
    normalize_futures_chain,
    normalize_futures_depth,
    normalize_history,
    normalize_options_oi,
    normalize_quote,
)
from app.data.validation import validate_candles
from app.integrations.fyers.mock_responses import (
    mock_depth_response,
    mock_depth_response_missing_levels,
    mock_futures_depth_response,
    mock_history_response,
    mock_options_chain_response,
    mock_quotes_response,
)


def test_normalize_history_produces_sorted_candles():
    candles = normalize_history(mock_history_response(bars=30))
    assert len(candles) == 30
    assert all(c.high >= c.low for c in candles)
    assert [c.trade_date for c in candles] == sorted(c.trade_date for c in candles)


def test_normalize_quote_extracts_ltp():
    quote = normalize_quote(mock_quotes_response())
    assert quote is not None
    assert quote.ltp > 0
    assert quote.symbol == "NSE:RELIANCE-EQ"


def test_normalize_quote_handles_empty_payload():
    assert normalize_quote({"s": "ok", "d": []}) is None


def test_normalize_depth():
    depth = normalize_depth("NSE:RELIANCE-EQ", mock_depth_response())
    assert depth is not None
    assert depth.total_buy_qty > 0


def test_normalize_depth_preserves_5_bid_and_ask_levels():
    """Phase 6 market-depth investigation: FYERS' real response carries 5
    levels each side (confirmed live); the previous normalization discarded
    all of them and kept only the aggregate totals."""
    depth = normalize_depth("NSE:RELIANCE-EQ", mock_depth_response())

    assert len(depth.bid_levels) == 5
    assert len(depth.ask_levels) == 5
    assert depth.bid_levels[0].price == 2951.0
    assert depth.bid_levels[0].quantity == 500
    assert depth.bid_levels[0].order_count == 3
    assert depth.ask_levels[0].price == 2951.5
    assert depth.ask_levels[0].quantity == 620
    assert depth.ask_levels[0].order_count == 5


def test_normalize_depth_computes_top_of_book_and_spread():
    depth = normalize_depth("NSE:RELIANCE-EQ", mock_depth_response())
    assert depth.top_bid == 2951.0
    assert depth.top_ask == 2951.5
    assert round(depth.spread, 2) == 0.5


def test_normalize_depth_handles_missing_levels_without_fabricating_data():
    """Phase 6 requirement: a field FYERS doesn't provide must be None /
    empty, never invented."""
    depth = normalize_depth("NSE:RELIANCE-EQ", mock_depth_response_missing_levels())
    assert depth is not None
    assert depth.bid_levels == []
    assert depth.ask_levels == []
    assert depth.top_bid is None
    assert depth.top_ask is None
    assert depth.spread is None
    # totals are still real fields FYERS did provide (both zero here)
    assert depth.total_buy_qty == 0
    assert depth.total_sell_qty == 0


def test_normalize_futures_chain_finds_nothing_against_a_real_options_chain_shape():
    """Phase 1 F&O investigation: confirmed live that /data/options-chain
    never contains a FUT-symbol row -- only the underlying's own row (spot)
    plus CE/PE strikes. normalize_futures_chain's FUT filter is therefore
    expected to always return empty against this real shape; futures data
    comes from normalize_futures_depth instead (see below)."""
    contracts = normalize_futures_chain(mock_options_chain_response())
    assert contracts == []


def test_normalize_options_oi_extracts_call_put_aggregate():
    call_oi, put_oi = normalize_options_oi(mock_options_chain_response())
    assert call_oi == 4_500_000
    assert put_oi == 5_100_000


def test_normalize_futures_depth_extracts_oi_and_price_change():
    symbol = "NSE:RELIANCE26SEPFUT"
    contract = normalize_futures_depth(mock_futures_depth_response(symbol), symbol)
    assert contract is not None
    assert contract.symbol == symbol
    assert contract.ltp == 1242.0
    assert contract.open_interest == 127_287_000
    assert contract.oi_change_pct == 2.4
    assert contract.volume == 10_342_500
    assert contract.price_change_pct == -0.43


def test_normalize_futures_depth_returns_none_for_missing_symbol():
    assert normalize_futures_depth({"s": "ok", "d": {}}, "NSE:RELIANCE26SEPFUT") is None


def test_validate_candles_flags_insufficient_history():
    candles = normalize_history(mock_history_response(bars=10))
    result = validate_candles(candles, min_history_days=100)
    assert result.is_valid is False
    assert any("insufficient_history" in issue for issue in result.issues)


def test_validate_candles_passes_clean_data():
    candles = normalize_history(mock_history_response(bars=120))
    result = validate_candles(candles, min_history_days=100)
    assert result.is_valid is True
    assert result.issues == []
