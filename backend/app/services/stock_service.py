"""Builds one fully-scored CandidateResponse for a single symbol.

This is the shared core used by both scanner_service.py (batch scan) and the
GET /api/stocks/{symbol}/analysis endpoint (single-stock deep dive), so the
two never compute different numbers for the same stock.

Pipeline order matches the architecture in the spec:
  data (FYERS + DB) -> validation -> normalization -> technical/volume/fno/
  fundamentals/news/relative-strength/sector -> institutional footprint ->
  setup detection -> scoring -> risk/position sizing -> scenarios ->
  data quality. AI narration is NOT generated here -- it's an explicit,
  separate call (see app/ai/research_engine.py) so it always runs last.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_MIN_HISTORY_DAYS
from app.data.internal_models import Candle
from app.data.normalization import normalize_history
from app.data.sector_index_map import get_sector_index_symbol
from app.data.universe import NIFTY_INDEX_SYMBOL, UniverseEntry
from app.data.validation import has_sufficient_liquidity, is_penny_stock, validate_candles
from app.db.redis_client import get_redis
from app.engines import (
    fno_engine,
    fundamental_engine,
    institutional_footprint_engine,
    market_sector_engine,
    news_engine,
    relative_strength_engine,
    risk_engine,
    scenario_engine,
    scoring_engine,
    setup_detection_engine,
    technical_engine,
    volume_engine,
)
from app.engines.data_quality_engine import compute_data_quality
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.historical_data import get_daily_history
from app.models.fundamentals import Fundamentals
from app.models.news import NewsItem
from app.models.stock import Stock
from app.schemas.common import EvidenceItem
from app.schemas.scanner import CandidateResponse
from app.schemas.settings import ScannerSettings
from app.schemas.stock import RelativeStrengthData, SectorData
from app.services import delivery_service, fno_service, news_service
from app.services.cache_service import (
    TTL_SECTOR_HISTORY_SECONDS,
    TTL_STOCK_HISTORY_SECONDS,
    get_json,
    sector_history_key,
    set_json,
    stock_history_key,
)


class CandidateRejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class StockContext:
    """Everything the scoring pipeline needs for one symbol, fetched once."""

    candles: list[Candle]
    nifty_candles: list[Candle]
    sector_candles: list[Candle] | None
    fundamentals: Fundamentals | None
    news_items: list[NewsItem]


async def _fetch_history(client: FyersClient, symbol: str, days: int = 320) -> list[Candle]:
    # 320 calendar days, not 260: confirmed live that FYERS only returns
    # ~176 real trading candles for a 260-day window (weekends/holidays
    # strip ~32%), short of the 200 the technical engine needs for EMA200 --
    # mock data never caught this since its generator fabricates one candle
    # per calendar day, weekends included.
    #
    # Cached in Redis (TTL_STOCK_HISTORY_SECONDS): every caller here always
    # requests the same "last `days` days from today" window (confirmed --
    # backtest_service.py, the only caller needing arbitrary historical
    # windows, calls get_daily_history directly, never this function), so a
    # symbol-keyed cache is safe. Without this, a 20-stock scan re-fetched
    # all 20 stocks' full daily history from FYERS every single run, even
    # seconds apart -- the dominant contributor to the rate-limit-driven
    # candidate-selection variance seen earlier. Skipped in mock mode since
    # tests/mock data are expected fresh per call, not cached.
    range_to = dt.date.today()
    range_from = range_to - dt.timedelta(days=days)

    if client.use_mock:
        raw = await get_daily_history(client, symbol, range_from, range_to)
        return normalize_history(raw)

    redis = get_redis()
    cache_key = stock_history_key(symbol)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return _deserialize_candles(cached)

    raw = await get_daily_history(client, symbol, range_from, range_to)
    candles = normalize_history(raw)
    await set_json(redis, cache_key, _serialize_candles(candles), TTL_STOCK_HISTORY_SECONDS)
    return candles


def _serialize_candles(candles: list[Candle]) -> dict:
    return {
        "candles": [
            {"trade_date": c.trade_date.isoformat(), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
            for c in candles
        ]
    }


def _deserialize_candles(raw: dict) -> list[Candle]:
    return [
        Candle(
            trade_date=dt.date.fromisoformat(c["trade_date"]),
            open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"],
        )
        for c in raw["candles"]
    ]


async def get_sector_candles(client: FyersClient, sector_name: str | None) -> list[Candle] | None:
    """Fetches the mapped sector index's daily history (section 10/14), used
    for real sector-vs-NIFTY relative strength instead of leaving it null.
    Returns None when the sector has no confirmed index mapping (see
    app/data/sector_index_map.py) -- callers must treat that as
    "unavailable", never as a flat/neutral reading.

    Cached in Redis (TTL_SECTOR_HISTORY_SECONDS) since many stocks in the
    same scan run share a sector and would otherwise refetch identical
    history repeatedly.
    """
    index_symbol = get_sector_index_symbol(sector_name)
    if index_symbol is None:
        return None

    redis = get_redis()
    cache_key = sector_history_key(sector_name)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return _deserialize_candles(cached)

    candles = await _fetch_history(client, index_symbol)
    await set_json(redis, cache_key, _serialize_candles(candles), TTL_SECTOR_HISTORY_SECONDS)
    return candles


async def get_or_create_stock_row(db: AsyncSession, universe_entry: UniverseEntry) -> Stock:
    """News (and, via the scanner's own _ensure_stock_rows, everything else)
    needs a real stock_id to attach rows to. The scanner already creates
    these up front, but the single-stock analysis endpoint can be called for
    a symbol that's never been scanned, so this is idempotent and safe to
    call from either path.
    """
    row = (await db.execute(select(Stock).where(Stock.symbol == universe_entry.symbol))).scalar_one_or_none()
    if row is not None:
        return row

    row = Stock(
        symbol=universe_entry.symbol,
        exchange="NSE",
        company_name=universe_entry.company_name,
        sector=universe_entry.sector,
        is_fno=universe_entry.is_fno,
        is_mtf_eligible=universe_entry.is_mtf_eligible,
        is_liquid=True,
        is_active=True,
    )
    db.add(row)
    await db.flush()
    return row


async def load_stock_context(
    client: FyersClient,
    db: AsyncSession,
    universe_entry: UniverseEntry,
    nifty_candles: list[Candle],
) -> StockContext:
    candles = await _fetch_history(client, universe_entry.symbol)
    sector_candles = await get_sector_candles(client, universe_entry.sector)

    stock_row = await get_or_create_stock_row(db, universe_entry)

    fundamentals_row = (
        await db.execute(select(Fundamentals).where(Fundamentals.stock_id == stock_row.id))
    ).scalar_one_or_none()

    news_rows = await news_service.get_fresh_news_for_stock(
        db, stock_row.id, universe_entry.symbol, universe_entry.company_name
    )

    return StockContext(
        candles=candles,
        nifty_candles=nifty_candles,
        sector_candles=sector_candles,
        fundamentals=fundamentals_row,
        news_items=list(news_rows),
    )


async def build_candidate(
    client: FyersClient,
    universe_entry: UniverseEntry,
    context: StockContext,
    settings: ScannerSettings,
    available_capital: float = 100000.0,
    risk_percent: float = 2.0,
) -> CandidateResponse:
    """Raises CandidateRejected if hard filters (section 16) fail."""

    candles = context.candles
    validation = validate_candles(candles, settings.min_history_days or DEFAULT_MIN_HISTORY_DAYS)
    if not validation.is_valid and len(candles) < settings.min_history_days:
        raise CandidateRejected(f"insufficient_or_invalid_data: {validation.issues}")

    last_close = candles[-1].close
    if settings.exclude_penny_stocks and is_penny_stock(last_close, settings.min_price):
        raise CandidateRejected(f"penny_stock_price_below_{settings.min_price}")

    avg_volume_20d = sum(c.volume for c in candles[-20:]) / min(20, len(candles))
    avg_turnover_20d = avg_volume_20d * last_close
    if not has_sufficient_liquidity(
        avg_volume_20d, avg_turnover_20d, settings.min_avg_daily_volume, settings.min_avg_daily_turnover
    ):
        raise CandidateRejected("insufficient_liquidity")

    if settings.mtf_eligible_only and not universe_entry.is_mtf_eligible:
        raise CandidateRejected("not_mtf_eligible")

    if settings.fno_only and not universe_entry.is_fno:
        raise CandidateRejected("not_fno_stock")

    # --- Calculations (technical, volume) ---
    technical = technical_engine.compute_technical_metrics(candles)
    volume = volume_engine.compute_volume_metrics(candles)

    # --- Relative strength / sector ---
    relative_strength = relative_strength_engine.compute_relative_strength(
        candles, context.nifty_candles, context.sector_candles
    )
    sector_data: SectorData = market_sector_engine.build_sector_data(
        universe_entry.sector, context.sector_candles, context.nifty_candles, relative_strength
    )

    ticker = universe_entry.symbol.split(":")[-1].split("-")[0]

    # --- F&O (Phase 1/3 investigations: see app/services/fno_service.py for
    # why this is two independent, individually-cached FYERS calls) ---
    if universe_entry.is_fno:
        futures, call_oi_total, put_oi_total = await fno_service.get_fno_data(client, universe_entry.symbol, ticker)
        fno_data = fno_engine.compute_fno_metrics(True, futures, call_oi_total, put_oi_total)
    else:
        fno_data = fno_engine.compute_fno_metrics(False, None)

    # --- Fundamentals / news ---
    fundamental_data = fundamental_engine.build_fundamental_data(context.fundamentals)
    news_data = news_engine.build_news_data(context.news_items)

    # --- Institutional footprint (delivery data is a single shared, Redis-
    # cached fetch for the whole market -- see delivery_service.py) ---
    delivery = await delivery_service.get_delivery_metrics(ticker)
    footprint = institutional_footprint_engine.compute_institutional_footprint(
        volume, relative_strength, fno_data, delivery
    )

    # --- Setup detection ---
    setup = setup_detection_engine.detect_setup(technical, volume, relative_strength)

    # --- Data quality ---
    now = dt.datetime.now(dt.UTC)
    available_sources = {"price_history", "volume_metrics"}
    if fno_data.is_available:
        available_sources.add("fno_metrics")
    if fundamental_data.is_available:
        available_sources.add("fundamentals")
    if news_data.items:
        available_sources.add("news")
    if sector_data.sector_strength_label is not None:
        available_sources.add("sector_metrics")
    source_timestamps = {s: now for s in available_sources}
    data_quality = compute_data_quality(source_timestamps, available_sources)

    # --- Scoring ---
    total_score, components, signal_quality = scoring_engine.compute_score(
        technical, volume, relative_strength, fno_data, fundamental_data, news_data,
        sector_data, data_quality.data_quality_score,
    )

    # --- Scenarios & risk (position sizing uses caller-provided capital/risk at request time) ---
    scenarios = scenario_engine.build_scenarios(last_close, technical)

    evidence: list[EvidenceItem] = list(footprint.evidence) + list(volume.evidence)
    risks: list[str] = []
    if technical.rsi_14 is not None and technical.rsi_14 >= 75:
        risks.append("RSI is in overbought territory -- pullback risk is elevated.")
    if footprint.institutional_footprint_level == "INSUFFICIENT_DATA":
        risks.append("Institutional footprint proxy could not be computed from available data.")
    if not fundamental_data.is_available:
        risks.append("Fundamental data is unavailable for this stock.")
    if not fno_data.is_available:
        risks.append("F&O positioning is unavailable (not an F&O stock or feed missing).")
    if data_quality.missing_data:
        risks.append(f"Missing data sources: {', '.join(data_quality.missing_data)}.")

    return CandidateResponse(
        symbol=universe_entry.symbol,
        company_name=universe_entry.company_name,
        sector=universe_entry.sector,
        score=total_score,
        score_components=components,
        signal_quality=signal_quality,
        price=round(last_close, 2),
        entry_zone_low=scenarios.entry_zone_low,
        entry_zone_high=scenarios.entry_zone_high,
        invalidation=scenarios.invalidation,
        scenarios=scenarios,
        setup=setup,
        institutional_footprint=footprint,
        technical=_technical_result_to_schema(technical),
        volume=_volume_result_to_schema(volume),
        fno=fno_data,
        fundamentals=fundamental_data,
        relative_strength=relative_strength,
        sector_context=sector_data,
        news=news_data,
        position_sizing=risk_engine.compute_position_size(
            available_capital=available_capital,
            risk_percent=risk_percent,
            entry_price=scenarios.preferred_entry,
            invalidation_price=scenarios.invalidation,
            resistance_scenario_1=scenarios.resistance_scenario_1,
            resistance_scenario_2=scenarios.resistance_scenario_2,
        ),
        evidence=evidence,
        risks=risks,
        data_quality=data_quality,
    )


def _technical_result_to_schema(technical: technical_engine.TechnicalResult):
    from app.schemas.stock import TechnicalData

    return TechnicalData(**technical.__dict__)


def _volume_result_to_schema(volume: volume_engine.VolumeResult):
    from app.schemas.stock import VolumeData

    d = dict(volume.__dict__)
    d.pop("avg_volume_20d", None)
    d.pop("consolidation_volume_avg", None)
    return VolumeData(**d)


async def get_nifty_candles(client: FyersClient) -> list[Candle]:
    return await _fetch_history(client, NIFTY_INDEX_SYMBOL)
