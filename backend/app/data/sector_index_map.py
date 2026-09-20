"""Maps `Stock.sector` labels (as assigned in app/data/universe.py) to a real
FYERS index symbol, so market_sector_engine.py can compute genuine
sector-vs-NIFTY relative strength instead of leaving it null.

Symbol format (`NSE:<INDEX>-INDEX`) and every ticker below are verified
directly against the live FYERS NSE_CM.csv symbol master (Phase 5
investigation, 2026-09-20) -- both that the symbol string is real (not
guessed/pattern-derived) and that /data/history actually returns candles
for it, not invented. "IT", "Financials", "Auto", "Pharma", "FMCG",
"Energy", "Power" were already correctly mapped and verified live to still
work -- they are NOT part of the sectors this investigation found missing.

"Consumer Durables" was added this pass: the real FYERS symbol is
NSE:NIFTYCONSRDURBL-INDEX (Nifty Consumer Durables, NSE-launched 2020;
confirmed live to return real candles). Note the FYERS ticker itself uses
"CONSRDURBL", not the more guessable "CONSDURBL"/"CONSUMERDUR" -- those
both 422 as invalid symbols, which is exactly why this map must be verified
against the real symbol master rather than pattern-derived.

"Telecom", "Cement", "Diversified", "Industrials" remain deliberately OUT
of this map (falls back to None -> sector strength stays unavailable,
never a fabricated/positive score) after scanning FYERS' full live list of
119 NIFTY-prefixed index symbols: NSE does not publish a standalone
sectoral index for any of the four (cement/telecom/diversified conglomerate
holdings are too few large-cap constituents to index separately on NSE;
"industrials" is covered only by broad multi-sector indices like
NIFTYINDIAMFG/NIFTYMULTIMFG/NIFTYMULTIINFRA, none of which is a credible
1:1 sector proxy the way NIFTYENERGY is for "Power").

"Power" maps to NIFTYENERGY: NSE does not publish a standalone power-sector
index, and NTPC/POWER GRID are themselves constituents of NIFTY Energy, so
that index is the closest real, non-invented proxy -- a domain judgment
call, not a literal 1:1 label match.
"""

SECTOR_INDEX_MAP: dict[str, str] = {
    "IT": "NSE:NIFTYIT-INDEX",
    "Financials": "NSE:FINNIFTY-INDEX",
    "Auto": "NSE:NIFTYAUTO-INDEX",
    "Pharma": "NSE:NIFTYPHARMA-INDEX",
    "FMCG": "NSE:NIFTYFMCG-INDEX",
    "Energy": "NSE:NIFTYENERGY-INDEX",
    "Power": "NSE:NIFTYENERGY-INDEX",
    "Consumer Durables": "NSE:NIFTYCONSRDURBL-INDEX",
}


def get_sector_index_symbol(sector_name: str | None) -> str | None:
    if sector_name is None:
        return None
    return SECTOR_INDEX_MAP.get(sector_name)
