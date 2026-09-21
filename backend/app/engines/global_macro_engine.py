"""Turns raw global macro quotes (app/services/global_macro_service.py) into
contextual evidence for one candidate's sector (research layer, Phase 5).

Deliberately does NOT implement simplistic rules like "Nasdaq up = Indian
stocks bullish" or "crude up = all oil stocks bullish" (explicit
requirement). Two separate things come out of this module:

1. `risk_sentiment` (RISK_ON/RISK_OFF/MIXED/INSUFFICIENT_DATA): a small,
   NUMERICALLY-WEIGHTED research-score input (see RESEARCH_WEIGHTS'
   market_regime_and_global_sentiment bucket) derived ONLY from the broad
   global equity indices -- a defensible, low-specificity "risk-on/risk-off"
   read, not a stock-level call.
2. `sector_specific_notes`: QUALITATIVE evidence only (SECTOR_MACRO_MAP
   below), e.g. USD/INR for IT/Pharma exporters, crude for Auto/Cement input
   costs. These never move the numeric score directly -- they feed
   conflict/support detection (research_confirmation_engine.py) as
   descriptive, hedged context, exactly because "crude up -> bad for Auto"
   is too simplistic to price as an independent point value.

Every item carries `session_state` (see MacroSessionState) so a closed
market's last-known snapshot is never presented as a live move.
"""

import datetime as dt

from app.core.constants import GlobalRiskSentiment, MacroSessionState
from app.data.global_macro_parser import MacroQuote
from app.schemas.research import GlobalMacroContext, MacroContextItem

# Instruments used for the broad, sector-agnostic risk-sentiment read.
_BROAD_RISK_LABELS = ("S&P 500", "Nasdaq", "Dow Jones", "Nikkei 225", "Hang Seng")

# A snapshot older than this is treated as a closed/last-available session,
# never a live move -- matches the spirit of market_data_service.py's
# freshness classification, but Yahoo's semantics (a session close, not a
# streaming tick) mean a longer window is appropriate here than the FYERS
# live-quote 15-30s threshold.
_LIVE_SESSION_MAX_AGE_SECONDS = 900  # 15 minutes

# sector -> [(macro_label, hedged interpretation)]. Deliberately short and
# specific: only sectors present in app/data/universe.py with a defensible,
# documented rationale get an entry. No entry for a sector means "no macro
# overlay claimed" -- never a fabricated one.
SECTOR_MACRO_MAP: dict[str, list[tuple[str, str]]] = {
    "IT": [
        ("USD/INR", "A weaker rupee (USD/INR up) is contextually favorable for IT exporters' "
                     "rupee-denominated revenue -- macro context, not a standalone signal."),
    ],
    "Pharma": [
        ("USD/INR", "A weaker rupee (USD/INR up) is contextually favorable for pharma exporters' "
                     "rupee-denominated revenue -- macro context, not a standalone signal."),
    ],
    "Auto": [
        ("WTI Crude", "Higher crude raises fuel/input costs and dampens consumer fuel-cost sensitivity "
                       "for auto manufacturers -- an adverse cost-context signal, not a directional call."),
    ],
    "Cement": [
        ("WTI Crude", "Cement production is energy-intensive; higher crude/energy prices raise input "
                       "costs -- adverse cost context only, not a directional call."),
    ],
    "Energy": [
        ("WTI Crude", "This universe's Energy-sector stock(s) mix upstream and refining/petrochemical "
                       "exposure -- crude direction's net earnings effect depends on business mix and is "
                       "deliberately NOT assigned a single direction here."),
    ],
}


def classify_macro_session_state(as_of: dt.datetime, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    age_seconds = (now - as_of).total_seconds()
    return (
        MacroSessionState.LIVE_SESSION.value
        if age_seconds <= _LIVE_SESSION_MAX_AGE_SECONDS
        else MacroSessionState.LAST_AVAILABLE_SNAPSHOT.value
    )


def _to_context_item(quote: MacroQuote, affected_dimension: str, interpretation: str, confidence: str) -> MacroContextItem:
    return MacroContextItem(
        label=quote.label,
        symbol=quote.symbol,
        value=quote.price,
        change_pct=quote.change_pct,
        as_of=quote.as_of,
        session_state=classify_macro_session_state(quote.as_of),
        affected_dimension=affected_dimension,
        interpretation=interpretation,
        confidence=confidence,
        source=quote.source,
    )


def _classify_risk_sentiment(quotes_by_label: dict[str, MacroQuote]) -> str:
    changes = [
        quotes_by_label[label].change_pct
        for label in _BROAD_RISK_LABELS
        if label in quotes_by_label and quotes_by_label[label].change_pct is not None
    ]
    if not changes:
        return GlobalRiskSentiment.INSUFFICIENT_DATA.value

    up = sum(1 for c in changes if c > 0)
    down = sum(1 for c in changes if c < 0)
    if up == down:
        return GlobalRiskSentiment.MIXED.value
    return GlobalRiskSentiment.RISK_ON.value if up > down else GlobalRiskSentiment.RISK_OFF.value


def build_global_macro_context(macro_quotes: list[MacroQuote], sector: str | None) -> GlobalMacroContext:
    if not macro_quotes:
        return GlobalMacroContext(
            risk_sentiment=GlobalRiskSentiment.INSUFFICIENT_DATA.value,
            broad_instruments=[],
            sector_specific_notes=[],
            source="Yahoo Finance (unofficial API) -- no quotes available this run",
        )

    quotes_by_label = {q.label: q for q in macro_quotes}
    source_label = macro_quotes[0].source

    broad_instruments = [
        _to_context_item(
            quotes_by_label[label],
            affected_dimension="Broad risk sentiment (all sectors, context only)",
            interpretation=(
                f"{label} is a general global risk-sentiment input, not a direct signal for any single "
                "Indian stock or sector."
            ),
            confidence="LOW",
        )
        for label in _BROAD_RISK_LABELS
        if label in quotes_by_label
    ]
    # US 10Y and Gold are carried as broad context too (Step 4: "contextual
    # risk/liquidity input", "primarily risk/macro context") -- not part of
    # the risk_sentiment vote above (that's equity-indices only, deliberately
    # narrower and more defensible), but still surfaced as evidence.
    for label, note in (
        ("US 10Y Yield", "A contextual risk/liquidity input (higher yields -> tighter global liquidity) -- "
                          "not an automatic directional stock signal."),
        ("Gold", "Primarily a risk/macro-hedge context signal, not directly relevant to any sector in this "
                 "universe unless the candidate has direct gold-sector exposure (none currently in scope)."),
    ):
        if label in quotes_by_label:
            broad_instruments.append(
                _to_context_item(quotes_by_label[label], affected_dimension="Broad macro/risk context", interpretation=note, confidence="LOW")
            )

    sector_specific_notes = [
        _to_context_item(quotes_by_label[label], affected_dimension=f"{sector} sector", interpretation=note, confidence="MEDIUM")
        for label, note in SECTOR_MACRO_MAP.get(sector or "", [])
        if label in quotes_by_label
    ]

    return GlobalMacroContext(
        risk_sentiment=_classify_risk_sentiment(quotes_by_label),
        broad_instruments=broad_instruments,
        sector_specific_notes=sector_specific_notes,
        source=source_label,
    )
