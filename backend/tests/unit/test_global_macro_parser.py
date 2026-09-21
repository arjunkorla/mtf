from app.data.global_macro_parser import normalize_macro_quote
from app.integrations.global_macro.yahoo_finance_client import _MOCK_CHART_RESPONSES


def test_normalize_macro_quote_extracts_real_fields():
    quote = normalize_macro_quote(_MOCK_CHART_RESPONSES["^GSPC"], "S&P 500")
    assert quote is not None
    assert quote.label == "S&P 500"
    assert quote.symbol == "^GSPC"
    assert quote.price == 7650.5
    assert quote.prev_close == 7637.76
    assert quote.change_pct == 0.167
    assert "unofficial" in quote.source.lower()


def test_normalize_macro_quote_returns_none_when_price_missing():
    raw = {"chart": {"result": [{"meta": {"symbol": "^GSPC"}}]}}
    assert normalize_macro_quote(raw, "S&P 500") is None


def test_normalize_macro_quote_returns_none_for_empty_result():
    assert normalize_macro_quote({"chart": {"result": None}}, "S&P 500") is None
    assert normalize_macro_quote({"chart": {"result": []}}, "S&P 500") is None


def test_normalize_macro_quote_handles_malformed_payload():
    assert normalize_macro_quote({}, "S&P 500") is None
    assert normalize_macro_quote({"chart": None}, "S&P 500") is None
