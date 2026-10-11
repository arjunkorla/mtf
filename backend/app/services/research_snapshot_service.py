"""Research observation collection orchestrator (Phase 6, Objectives 1-5, 9).

RUN NORMAL SCANNER (unmodified) -> take its actual candidates -> subscribe
them through the shared LiveDataHub -> let the live cache populate -> build
Research Confirmation for each -> persist ONE market-wide snapshot plus one
observation per candidate.

Never invents a collection: only runs during real NSE market hours, only at
a configured slot (within tolerance), and only once per (session_date,
slot) -- see _resolve_collection_slot(). If the process isn't running at a
configured time, the slot is simply never collected; nothing here backdates
or fabricates a missing observation.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.engines.global_macro_engine import build_global_macro_context
from app.engines.india_vix_engine import classify_vix_regime
from app.engines.market_sector_engine import compute_market_regime
from app.engines.relative_strength_engine import pct_return
from app.engines.research_confirmation_engine import build_india_vix_context, build_research_confirmation
from app.engines.research_divergence_engine import classify_divergence
from app.engines.sector_participation_engine import classify_sector_participation
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import get_logger
from app.models.research_market_snapshot import ResearchMarketSnapshot
from app.models.research_observation import ResearchObservation
from app.schemas.scanner import CandidateResponse, ScannerRunRequest
from app.schemas.research import ResearchConfirmation
from app.services.candidate_live_subscription_service import collect_live_quotes_for_candidates
from app.services.market_data_service import get_cached_live_quote, is_market_hours_ist
from app.services.global_macro_service import get_global_macro_snapshot
from app.services.research_confirmation_service import _fetch_india_vix
from app.services.realtime_confirmation_service import get_realtime_confirmation
from app.services.scanner_service import run_scanner
from app.services.settings_service import get_scanner_settings
from app.services.stock_service import _fetch_history, get_nifty_candles, get_sector_candles

logger = get_logger(__name__)


def _configured_slots(settings: Settings) -> list[dt.time]:
    slots = []
    for raw in settings.research_collection_slots_ist.split(","):
        raw = raw.strip()
        if not raw:
            continue
        hour, minute = raw.split(":")
        slots.append(dt.time(int(hour), int(minute)))
    return slots


def resolve_collection_slot(now_ist: dt.datetime, settings: Settings | None = None) -> str | None:
    """Returns the configured slot label ("10:30") `now_ist` falls within
    `research_slot_tolerance_minutes` of, or None if it matches no
    configured slot -- the mechanism behind "do not fabricate a missing
    observation" when the process isn't running at a configured time."""
    settings = settings or get_settings()
    tolerance = dt.timedelta(minutes=settings.research_slot_tolerance_minutes)
    today_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    for slot in _configured_slots(settings):
        slot_dt = today_midnight.replace(hour=slot.hour, minute=slot.minute)
        if abs(now_ist - slot_dt) <= tolerance:
            return f"{slot.hour:02d}:{slot.minute:02d}"
    return None


def _delivery_state(candidate: CandidateResponse) -> str | None:
    item = next((e for e in candidate.institutional_footprint.evidence if e.label == "Delivery behaviour proxy"), None)
    return item.detail if item is not None else None


def _live_confirmation_coverage(candidate: CandidateResponse, research: ResearchConfirmation) -> dict:
    realtime = research.live_confirmation
    return {
        "historical_price": True,  # the candidate exists, so daily history was available
        "live_quote": realtime is not None and realtime.freshness not in ("UNAVAILABLE", None),
        "market_depth": realtime is not None and realtime.depth_confirmation.status != "UNAVAILABLE",
        "delivery": _delivery_state(candidate) is not None,
        "futures": candidate.fno.is_available,
        "options": candidate.fno.put_call_oi_ratio is not None,
        "sector": candidate.sector_context.sector_strength_label is not None,
        "india_vix": research.india_vix_context.value is not None,
        "global_macro": research.global_macro_context.risk_sentiment != "INSUFFICIENT_DATA",
        "news": bool(candidate.news.items),
        "corporate_events": False,
    }


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def collection_clock(now_utc: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """(now_utc, now_ist) as the SAME instant. Phase D fix: this used to be
    `now_utc + 5:30` with UTC tzinfo still attached, which stored an instant
    5.5h in the future in the timestamptz `timestamp_ist` columns. now_ist
    is a real IST-aware datetime used only for IST wall-clock logic (slot,
    session date); the persisted `timestamp_ist` columns receive the UTC
    instant (one convention: persist UTC, convert to IST for display --
    SQLite would otherwise keep IST wall time and drop the offset)."""
    return now_utc, now_utc.astimezone(IST)


async def collect_research_snapshot(db: AsyncSession, redis, request: ScannerRunRequest) -> dict:
    settings = get_settings()
    now_utc, now_ist = collection_clock(dt.datetime.now(dt.UTC))

    if not is_market_hours_ist(now_utc):
        return {"status": "SKIPPED_NOT_MARKET_HOURS", "timestamp_ist": now_ist.isoformat()}

    slot = resolve_collection_slot(now_ist, settings)
    if slot is None:
        return {"status": "SKIPPED_NOT_A_COLLECTION_WINDOW", "timestamp_ist": now_ist.isoformat()}

    session_date = now_ist.date()
    existing = (
        await db.execute(
            select(ResearchMarketSnapshot).where(
                ResearchMarketSnapshot.session_date == session_date, ResearchMarketSnapshot.slot_label == slot
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"status": "SKIPPED_ALREADY_COLLECTED", "slot": slot, "snapshot_id": existing.id}

    scanner_settings = await get_scanner_settings(redis)
    scan_result = await run_scanner(request, db, scanner_settings)  # the REAL, unmodified production scanner
    if not scan_result.candidates:
        return {"status": "SKIPPED_NO_CANDIDATES", "slot": slot}

    candidates = scan_result.candidates
    symbols = [c.symbol for c in candidates]

    await collect_live_quotes_for_candidates(symbols, settings=settings)

    client = FyersClient()
    try:
        macro_quotes = await get_global_macro_snapshot()
        vix, vix_source = await _fetch_india_vix(client)
        nifty_candles = await get_nifty_candles(client)
        nifty_regime = compute_market_regime(nifty_candles)
        market_macro = build_global_macro_context(macro_quotes, sector=None)

        snapshot = ResearchMarketSnapshot(
            session_date=session_date, timestamp_utc=now_utc, timestamp_ist=now_utc, slot_label=slot,
            nifty_regime=nifty_regime, india_vix=vix, vix_regime=classify_vix_regime(vix),
            global_risk_sentiment=market_macro.risk_sentiment,
            global_macro_payload=market_macro.model_dump(mode="json"),
            source_provenance={"global_macro": market_macro.source, "india_vix": vix_source or "unavailable this run"},
        )
        db.add(snapshot)
        await db.flush()

        mtf_ranked = sorted(candidates, key=lambda c: (-c.score, c.symbol))
        mtf_rank_by_symbol = {c.symbol: i + 1 for i, c in enumerate(mtf_ranked)}

        built: list[tuple[CandidateResponse, ResearchConfirmation]] = []
        for candidate in candidates:
            realtime = None
            try:
                realtime = await get_realtime_confirmation(candidate.symbol, candidate, client)
            except Exception as exc:  # noqa: BLE001 -- one symbol's confirmation outage must not sink the snapshot
                logger.warning("Real-time confirmation unavailable for %s: %s", candidate.symbol, exc)

            macro_context = build_global_macro_context(macro_quotes, candidate.sector)  # reuses the SAME already-fetched quotes
            vix_context = build_india_vix_context(vix, now_utc if vix is not None else None, vix_source)
            research = build_research_confirmation(candidate, realtime, macro_context, vix_context, now=now_utc)
            built.append((candidate, research))

        scored = [(c, r) for c, r in built if r.research_confirmation_score is not None]
        research_ranked = sorted(scored, key=lambda pair: (-pair[1].research_confirmation_score, pair[0].symbol))
        research_rank_by_symbol = {c.symbol: i + 1 for i, (c, _r) in enumerate(research_ranked)}

        observation_ids = []
        for candidate, research in built:
            stock_candles = await _fetch_history(client, candidate.symbol)
            sector_candles = await get_sector_candles(client, candidate.sector)

            stock_5d = pct_return(stock_candles, 5)
            stock_20d = pct_return(stock_candles, 20)
            sector_5d = pct_return(sector_candles, 5) if sector_candles else None
            sector_20d = pct_return(sector_candles, 20) if sector_candles else None

            participation, participation_evidence = classify_sector_participation(
                stock_20d, sector_20d, candidate.technical.trend_structure, stock_5d, sector_5d,
            )

            mtf_rank = mtf_rank_by_symbol.get(candidate.symbol)
            research_rank = research_rank_by_symbol.get(candidate.symbol)
            research_minus_mtf, rank_delta, divergence = classify_divergence(
                candidate.score, mtf_rank, research.research_confirmation_score, research_rank,
            )

            live_quote = await get_cached_live_quote(candidate.symbol)
            observed_price = live_quote["ltp"] if live_quote else candidate.price

            observation = ResearchObservation(
                session_date=session_date, timestamp_utc=now_utc, timestamp_ist=now_utc, symbol=candidate.symbol,
                market_snapshot_id=snapshot.id, observed_price=observed_price,
                mtf_score=candidate.score, mtf_rank=mtf_rank,
                research_confirmation_score=research.research_confirmation_score, research_rank=research_rank,
                research_status=research.research_status,
                technical_state=f"{candidate.technical.trend_structure}/{candidate.technical.breakout_status}",
                stock_return_5d=stock_5d, stock_return_20d=stock_20d,
                sector=candidate.sector, sector_state=candidate.sector_context.sector_strength_label,
                sector_return_5d=sector_5d, sector_return_20d=sector_20d,
                stock_vs_sector_5d=round(stock_5d - sector_5d, 3) if stock_5d is not None and sector_5d is not None else None,
                stock_vs_sector_20d=candidate.relative_strength.vs_sector_pct_20d,
                stock_vs_nifty_5d=None,  # no production 5D-vs-NIFTY calculation exists to reuse -- honest gap, not invented here
                stock_vs_nifty_20d=candidate.relative_strength.vs_nifty_pct_20d,
                sector_participation=participation,
                sector_participation_evidence=[e.model_dump(mode="json") for e in participation_evidence],
                volume_state=(f"{candidate.volume.volume_ratio:.2f}x 20D avg" if candidate.volume.volume_ratio is not None else None),
                delivery_state=_delivery_state(candidate),
                institutional_proxy=candidate.institutional_footprint.institutional_footprint_level,
                futures_state=candidate.fno.positioning_proxy,
                futures_oi_context={
                    "futures_oi_change_pct": candidate.fno.futures_oi_change_pct,
                    "futures_price_change_pct": candidate.fno.futures_price_change_pct,
                },
                options_context={"put_call_oi_ratio": candidate.fno.put_call_oi_ratio},
                live_confirmation_status=realtime.confirmation_status if realtime else None,
                live_confirmation_score=realtime.confirmation_score if realtime else None,
                market_regime=candidate.sector_context.market_regime,
                news_context=research.news_context.model_dump(mode="json"),
                corporate_event_context=research.corporate_event_context.model_dump(mode="json"),
                supporting_signals=research.supporting_signals,
                conflicting_signals=research.conflicting_signals,
                risk_signals=research.risk_signals,
                missing_data=research.missing_data,
                core_data_quality=research.core_data_quality.model_dump(mode="json"),
                research_data_coverage=research.research_data_coverage,
                live_confirmation_coverage=_live_confirmation_coverage(candidate, research),
                entry_zone={"low": candidate.entry_zone_low, "high": candidate.entry_zone_high},
                invalidation=candidate.invalidation,
                source_provenance=research.source_provenance,
                research_minus_mtf=research_minus_mtf,
                research_rank_minus_mtf_rank=rank_delta,
                divergence_classification=divergence,
                payload=research.model_dump(mode="json"),
            )
            db.add(observation)
            observation_ids.append(candidate.symbol)

        await db.commit()
        logger.info(
            "Research snapshot collected: slot=%s session_date=%s symbols=%s",
            slot, session_date, observation_ids,
        )
        return {
            "status": "COLLECTED", "slot": slot, "session_date": session_date.isoformat(),
            "snapshot_id": snapshot.id, "observation_count": len(observation_ids), "symbols": observation_ids,
        }
    finally:
        await client.aclose()
