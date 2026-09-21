import datetime as dt

from app.data.global_macro_parser import MacroQuote
from app.engines.global_macro_engine import build_global_macro_context, classify_macro_session_state


def _quote(label, symbol, change_pct, age_seconds=0.0, price=100.0):
    as_of = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=age_seconds)
    return MacroQuote(label=label, symbol=symbol, price=price, prev_close=price, change_pct=change_pct, as_of=as_of)


def test_session_state_fresh_quote_is_live_session():
    assert classify_macro_session_state(dt.datetime.now(dt.UTC)) == "LIVE_SESSION"


def test_session_state_old_quote_is_last_available_snapshot():
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(hours=6)
    assert classify_macro_session_state(stale) == "LAST_AVAILABLE_SNAPSHOT"


def test_no_quotes_yields_insufficient_data_never_fabricated():
    context = build_global_macro_context([], sector="IT")
    assert context.risk_sentiment == "INSUFFICIENT_DATA"
    assert context.broad_instruments == []
    assert context.sector_specific_notes == []


def test_majority_up_indices_yields_risk_on():
    quotes = [
        _quote("S&P 500", "^GSPC", 0.5), _quote("Nasdaq", "^IXIC", 0.3), _quote("Dow Jones", "^DJI", 0.1),
        _quote("Nikkei 225", "^N225", -0.2), _quote("Hang Seng", "^HSI", 0.4),
    ]
    context = build_global_macro_context(quotes, sector="Financials")
    assert context.risk_sentiment == "RISK_ON"


def test_majority_down_indices_yields_risk_off():
    quotes = [
        _quote("S&P 500", "^GSPC", -0.5), _quote("Nasdaq", "^IXIC", -0.3), _quote("Dow Jones", "^DJI", -0.1),
        _quote("Nikkei 225", "^N225", 0.2), _quote("Hang Seng", "^HSI", -0.4),
    ]
    context = build_global_macro_context(quotes, sector="Financials")
    assert context.risk_sentiment == "RISK_OFF"


def test_tied_indices_yields_mixed():
    quotes = [_quote("S&P 500", "^GSPC", 0.5), _quote("Nasdaq", "^IXIC", -0.5)]
    context = build_global_macro_context(quotes, sector="Financials")
    assert context.risk_sentiment == "MIXED"


def test_sector_specific_note_only_appears_for_mapped_sector():
    quotes = [_quote("USD/INR", "INR=X", 0.2), _quote("WTI Crude", "CL=F", -1.0)]
    it_context = build_global_macro_context(quotes, sector="IT")
    assert len(it_context.sector_specific_notes) == 1
    assert it_context.sector_specific_notes[0].label == "USD/INR"

    unmapped_context = build_global_macro_context(quotes, sector="Telecom")
    assert unmapped_context.sector_specific_notes == []


def test_closed_market_snapshot_is_never_labeled_as_live():
    stale_quote = _quote("S&P 500", "^GSPC", 0.1, age_seconds=6 * 3600)
    context = build_global_macro_context([stale_quote], sector="IT")
    assert context.broad_instruments[0].session_state == "LAST_AVAILABLE_SNAPSHOT"
