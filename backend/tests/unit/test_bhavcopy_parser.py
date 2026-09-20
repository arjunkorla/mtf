from app.data.bhavcopy_parser import parse_bhavcopy_csv
from app.integrations.nse.bhavcopy_client import _MOCK_BHAVCOPY_CSV


def test_parses_real_header_and_rows():
    result = parse_bhavcopy_csv(_MOCK_BHAVCOPY_CSV)
    assert result.rows_skipped == 0
    assert set(result.by_symbol) == {"20MICRONS", "RELIANCE", "TCS", "HDFCBANK", "INFY"}

    reliance = result.by_symbol["RELIANCE"]
    assert reliance.delivery_percentage == 77.01
    assert reliance.delivery_qty == 11645440
    assert reliance.total_traded_qty == 15122715


def test_filters_to_eq_series_only():
    csv_text = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
        "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "SOMEBOND, N0, 18-Sep-2026, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 100, 10.0, 5, 50, 50.0\n"
        "RELIANCE, EQ, 18-Sep-2026, 1243.90, 1245.00, 1247.30, 1226.40, 1226.40, 1226.40, 1234.75, "
        "15122715, 186728.32, 162092, 11645440, 77.01\n"
    )
    result = parse_bhavcopy_csv(csv_text)
    assert set(result.by_symbol) == {"RELIANCE"}
    assert result.rows_skipped == 0  # the bond row is a deliberate filter, not a validation failure


def test_skips_row_with_out_of_range_delivery_percentage():
    csv_text = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
        "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "BADSTOCK, EQ, 18-Sep-2026, 100, 100, 100, 100, 100, 100, 100, 1000, 1.0, 5, 500, 150.0\n"
    )
    result = parse_bhavcopy_csv(csv_text)
    assert result.by_symbol == {}
    assert result.rows_skipped == 1


def test_skips_row_with_missing_numeric_field():
    csv_text = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
        "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        "BROKEN, EQ, 18-Sep-2026, 100, 100, 100, 100, 100, 100, 100, 1000, 1.0, 5, 500, NA\n"
    )
    result = parse_bhavcopy_csv(csv_text)
    assert result.by_symbol == {}
    assert result.rows_skipped == 1


def test_empty_csv_yields_no_symbols():
    result = parse_bhavcopy_csv("")
    assert result.by_symbol == {}
    assert result.rows_seen == 0
