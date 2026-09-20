"""FYERS F&O adapters -- two independent, correctly-scoped data sources.

Conflating these was the root cause of F&O positioning always showing
unavailable (Phase 1 investigation, confirmed live 2026-09-20):

- get_options_chain(): /data/options-chain for a given underlying. This
  NEVER contains a FUT-symbol row for the underlying (only the spot row
  plus CE/PE strikes) -- but the spot row does carry live futures price
  fields (fp/fpch/fpchp), and the response's top-level callOi/putOi are a
  real options put/call Open Interest aggregate. Renamed from
  get_futures_chain, which mislabeled this as futures data.

- get_futures_depth(): /data/depth for the ACTUAL futures contract symbol
  (resolved via app/data/fo_symbol_master_parser.py). Confirmed live to be
  the only FYERS endpoint that returns futures Open Interest ('oi', 'pdoi',
  'oipercent') -- /data/quotes and /data/history do not carry OI for any
  symbol type (also confirmed against FYERS' own support documentation).

Interpretation into positioning proxies (long-buildup, short-covering, etc.)
happens in app/engines/fno_engine.py -- this module only fetches and returns
the provider's raw shape; app/data/normalization.py is what's allowed to
know the field names.
"""

from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.mock_responses import mock_futures_depth_response, mock_options_chain_response
from app.logging_config import get_logger

logger = get_logger(__name__)


async def get_options_chain(client: FyersClient, symbol: str) -> dict:
    if client.use_mock:
        return mock_options_chain_response(symbol)

    # `strikecount` reliably makes the real endpoint reject the request with
    # "Please provide valid inputs" (confirmed live, in any form -- string,
    # int, with or without a real expiry timestamp); omitting it is what
    # actually works, matching FYERS community examples.
    return await client.get_data("/options-chain", params={"symbol": symbol, "timestamp": ""})


async def get_futures_depth(client: FyersClient, futures_symbol: str) -> dict:
    """`futures_symbol` must be a real, currently-listed contract symbol
    (e.g. "NSE:RELIANCE26SEPFUT") resolved via fo_symbol_master_parser.py --
    this module has no knowledge of contract-month rollover."""
    if client.use_mock:
        return mock_futures_depth_response(futures_symbol)

    return await client.get_data("/depth", params={"symbol": futures_symbol, "ohlcv_flag": "1"})
