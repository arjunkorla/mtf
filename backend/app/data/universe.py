"""Configurable NSE stock universe (section 5).

`SEED_UNIVERSE` is a small, hand-picked set of liquid, well-known NSE
large/mid-cap symbols used for local development and tests when no live
FYERS symbol-master import has been run. It is intentionally NOT exhaustive
and must not be treated as investment guidance.

Production loading path (not implemented here): FYERS publishes a daily
symbol-master CSV per segment (NSE_CM/NSE_FO) -- a scheduled job should
download it, upsert into the `stocks` table, and flip `is_active` for
delisted symbols. That importer is a Phase 1 follow-up task, tracked as a
TODO rather than guessed at here since the exact CSV schema must be taken
from the live file, not invented.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str  # FYERS format, e.g. "NSE:RELIANCE-EQ"
    company_name: str
    sector: str
    is_fno: bool
    is_mtf_eligible: bool


SEED_UNIVERSE: list[UniverseEntry] = [
    UniverseEntry("NSE:RELIANCE-EQ", "Reliance Industries Ltd", "Energy", True, True),
    UniverseEntry("NSE:TCS-EQ", "Tata Consultancy Services Ltd", "IT", True, True),
    UniverseEntry("NSE:HDFCBANK-EQ", "HDFC Bank Ltd", "Financials", True, True),
    UniverseEntry("NSE:ICICIBANK-EQ", "ICICI Bank Ltd", "Financials", True, True),
    UniverseEntry("NSE:INFY-EQ", "Infosys Ltd", "IT", True, True),
    UniverseEntry("NSE:LT-EQ", "Larsen & Toubro Ltd", "Industrials", True, True),
    UniverseEntry("NSE:SBIN-EQ", "State Bank of India", "Financials", True, True),
    UniverseEntry("NSE:AXISBANK-EQ", "Axis Bank Ltd", "Financials", True, True),
    UniverseEntry("NSE:BHARTIARTL-EQ", "Bharti Airtel Ltd", "Telecom", True, True),
    UniverseEntry("NSE:MARUTI-EQ", "Maruti Suzuki India Ltd", "Auto", True, True),
    # NSE:TATAMOTORS-EQ no longer exists -- Tata Motors demerged into two
    # separately-listed companies (verified live against FYERS' NSE_CM.csv
    # symbol master, 2026-09-20): commercial vehicles (TMCV) and passenger
    # vehicles (TMPV). Only TMPV currently has active futures contracts
    # (verified against NSE_FO.csv) -- TMCV is not yet F&O-eligible.
    UniverseEntry("NSE:TMCV-EQ", "Tata Motors Limited", "Auto", False, True),
    UniverseEntry("NSE:TMPV-EQ", "Tata Motors Passenger Vehicles Ltd", "Auto", True, True),
    UniverseEntry("NSE:SUNPHARMA-EQ", "Sun Pharmaceutical Industries Ltd", "Pharma", True, True),
    UniverseEntry("NSE:TITAN-EQ", "Titan Company Ltd", "Consumer Durables", True, True),
    UniverseEntry("NSE:ULTRACEMCO-EQ", "UltraTech Cement Ltd", "Cement", True, True),
    UniverseEntry("NSE:BAJFINANCE-EQ", "Bajaj Finance Ltd", "Financials", True, True),
    UniverseEntry("NSE:ADANIENT-EQ", "Adani Enterprises Ltd", "Diversified", True, True),
    UniverseEntry("NSE:NTPC-EQ", "NTPC Ltd", "Power", True, True),
    UniverseEntry("NSE:POWERGRID-EQ", "Power Grid Corporation of India Ltd", "Power", True, True),
    UniverseEntry("NSE:HINDUNILVR-EQ", "Hindustan Unilever Ltd", "FMCG", True, True),
    UniverseEntry("NSE:KOTAKBANK-EQ", "Kotak Mahindra Bank Ltd", "Financials", True, True),
]

NIFTY_INDEX_SYMBOL = "NSE:NIFTY50-INDEX"


def get_seed_universe() -> list[UniverseEntry]:
    return list(SEED_UNIVERSE)
