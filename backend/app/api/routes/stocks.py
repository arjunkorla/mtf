"""GET /api/stocks/{symbol}, GET /api/stocks/{symbol}/analysis"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.research_engine import generate_research_note
from app.api.deps import get_db, get_redis_dep
from app.data.normalization import normalize_quote
from app.data.universe import get_seed_universe
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.quotes import get_quotes
from app.schemas.scanner import StockAnalysisResponse
from app.schemas.settings import ScannerSettings
from app.schemas.stock import MarketData, StockSummary
from app.services.cache_service import TTL_ANALYSIS_SECONDS, analysis_key, get_json, set_json
from app.services.stock_service import CandidateRejected, build_candidate, get_nifty_candles, load_stock_context

router = APIRouter()

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
QUOTE_AS_OF_BASIS = "QUOTE_SNAPSHOT_RETRIEVAL_TIME"  # not an exchange trade time; REST quotes may come from a <=15s cache


def _find_universe_entry(symbol: str):
    normalized = symbol.upper()
    for entry in get_seed_universe():
        if entry.symbol.upper() == normalized or entry.symbol.split(":")[-1].split("-")[0] == normalized:
            return entry
    return None


@router.get("/stocks/{symbol}", response_model=StockSummary)
async def get_stock(symbol: str) -> StockSummary:
    entry = _find_universe_entry(symbol)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the configured stock universe")
    return StockSummary(
        symbol=entry.symbol,
        company_name=entry.company_name,
        sector=entry.sector,
        is_fno=entry.is_fno,
        is_mtf_eligible=entry.is_mtf_eligible,
    )


@router.get("/stocks/{symbol}/analysis", response_model=StockAnalysisResponse)
async def get_stock_analysis(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> StockAnalysisResponse:
    entry = _find_universe_entry(symbol)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the configured stock universe")

    cache_key = analysis_key(entry.symbol)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return StockAnalysisResponse.model_validate(cached)

    client = FyersClient()
    try:
        nifty_candles = await get_nifty_candles(client)
        context = await load_stock_context(client, db, entry, nifty_candles)

        try:
            candidate = await build_candidate(client, entry, context, ScannerSettings())
        except CandidateRejected as exc:
            raise HTTPException(status_code=422, detail=f"{entry.symbol} failed candidate filters: {exc.reason}")

        quotes_raw = await get_quotes(client, [entry.symbol])
        retrieved_at = dt.datetime.now(dt.UTC)
        quote = normalize_quote(quotes_raw)
        # Phase D: FYERS /quotes carries no last-trade time -- its `tt` is a
        # session-date stamp (verified live 2026-09-29: 00:00 UTC, identical
        # for every symbol), which normalize_quote exposes as Quote.as_of. It
        # is therefore reported as the session date, and as_of is the snapshot
        # RETRIEVAL time, explicitly labelled -- never presented as a trade time.
        market_data = MarketData(
            price=quote.ltp if quote else candidate.price,
            change_pct=quote.change_pct if quote else None,
            volume=quote.volume if quote else None,
            avg_volume_20d=None,
            day_high=quote.high if quote else None,
            day_low=quote.low if quote else None,
            as_of=retrieved_at,
            as_of_basis=QUOTE_AS_OF_BASIS if quote else "SCAN_CLOSE_FALLBACK_NO_QUOTE",
            quote_session_date=quote.as_of.astimezone(IST).date() if quote else None,
        )

        ai_research = await generate_research_note(candidate)

        response = StockAnalysisResponse(
            symbol=entry.symbol,
            company_name=entry.company_name,
            market_data=market_data,
            candidate=candidate,
            ai_research=ai_research,
        )
        await set_json(redis, cache_key, response.model_dump(mode="json"), TTL_ANALYSIS_SECONDS)
        return response
    finally:
        await client.aclose()
