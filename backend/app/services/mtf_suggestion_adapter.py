"""MTF suggestion adapter (Phase C): turns an EXISTING, already-ranked MTF
scanner candidate into a TradeSuggestion creation request -- or rejects it
with explicit reasons.

It never recomputes the MTF score, never re-ranks, never mutates the
CandidateResponse, and never "improves" a level. Each level the scenario
engine produced is classified with the Phase A vocabulary by reproducing,
read-only, which branch of scenario_engine.build_scenarios() created it:

  support    = technical.support_level  (min(20D low, EMA50))  else PLACEHOLDER close*0.95
  resistance = technical.resistance_level (20D high)            else PLACEHOLDER close*1.05
  atr        = technical.atr_14                                  else PLACEHOLDER close*2%
  entry_low  = min(close, support + 0.25*ATR)
  entry_high = max(close, support + 0.75*ATR)
  stop       = support - 0.25*ATR
  target_1   = resistance
  target_2   = resistance + 2*ATR

A level built from a placeholder is FALLBACK. An entry bound that is the
scan-time close chosen by the min()/max() clamp is also FALLBACK: it is a
price anchor inserted so the zone contains the current price, not a
structure- or ATR-derived level. A value the adapter cannot reproduce is
UNAVAILABLE. Phase A validation (suggestion_level_validation.py) then
decides; it is not weakened here.

Generation price: a genuine LiveDataHub tick received within the freshness
threshold during NSE hours (MARKET_OPEN_LIVE). Stale,
unavailable, closed-market, auth-required and mock quotes are rejected --
the scan-time daily close is never presented as a live price.

Flags (config.py): ENABLE_MTF_SUGGESTION_ADAPTER=false,
MTF_SUGGESTION_DRY_RUN=true. Dry-run performs the full evaluation and
persists nothing.
"""

import dataclasses
import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import FyersAuthRequiredError
from app.core.suggestion_constants import (
    CreationStatus,
    Direction,
    LevelQuality,
    ObservationSource,
    ScannerType,
)
from app.data.nse_holidays import is_nse_trading_day
from app.data.session_calendar import nth_nse_session_after
from app.engines.suggestion_level_validation import LevelSpec, validate_levels
from app.logging_config import get_logger
from app.schemas.scanner import CandidateResponse
from app.schemas.suggestion import LevelInput, SuggestionCreateRequest
from app.services import suggestion_service as svc
from app.services.market_data_service import MARKET_STATUS_OPEN_LIVE, classify_market_status, is_market_hours_ist

logger = get_logger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
Q = LevelQuality
_EPS = 1e-6

# Generation-price states
PRICE_OK = "OK"
PRICE_STALE = "STALE"
PRICE_UNAVAILABLE = "UNAVAILABLE"
PRICE_AUTH_REQUIRED = "AUTH_REQUIRED"
PRICE_MOCK = "MOCK_DATA_REJECTED"
PRICE_MARKET_CLOSED = "MARKET_CLOSED"

# Run modes
MODE_DISABLED = "DISABLED"
MODE_DRY_RUN = "DRY_RUN"
MODE_PERSIST = "PERSIST"


@dataclasses.dataclass(frozen=True)
class GenerationQuote:
    status: str
    price: float | None = None
    at: dt.datetime | None = None  # last-trade time reported by the source
    fetched_at: dt.datetime | None = None
    source: str | None = None
    market_status: str | None = None
    detail: str | None = None


# ---- level provenance (read-only reproduction of scenario_engine) -----------------------------


def _same(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(round(a, 2) - round(b, 2)) < _EPS


def _support_desc(c: CandidateResponse) -> str:
    t = c.technical
    if t.recent_low_20d is not None and _same(t.support_level, t.recent_low_20d):
        return f"support = 20D low {t.support_level:.2f}"
    return f"support = EMA50 {t.support_level:.2f} (below 20D low)"


def _classify(value: float, structural: float | None, quality: LevelQuality, desc: str,
              placeholder_desc: str, close: float, clamp: bool) -> LevelInput:
    if structural is None:
        return LevelInput(price=value, quality=Q.FALLBACK.value, provenance=f"scenario_engine placeholder: {placeholder_desc}")
    if _same(value, structural):
        return LevelInput(price=value, quality=quality.value, provenance=desc)
    if clamp and _same(value, close):
        return LevelInput(
            price=value, quality=Q.FALLBACK.value,
            provenance=f"scan-time close {close:.2f} chosen by scenario_engine min/max clamp "
                       f"(structural value {structural:.2f}) -- price anchor, not a structure/ATR level",
        )
    return LevelInput(price=value, quality=Q.UNAVAILABLE.value,
                      provenance=f"could not reproduce scenario_engine value (expected {structural:.2f})")


def classify_levels(c: CandidateResponse) -> dict[str, LevelInput]:
    t, s = c.technical, c.scenarios
    close = c.price
    support, resistance, atr = t.support_level, t.resistance_level, t.atr_14
    have_sa = support is not None and atr is not None
    sdesc = _support_desc(c) if support is not None else "support unavailable"
    atr_desc = f"ATR14 {atr:.2f}" if atr is not None else "ATR14 unavailable"
    sa_placeholder = "support=close*0.95 and/or ATR=close*2%"

    return {
        "entry_low": _classify(
            c.entry_zone_low, support + 0.25 * atr if have_sa else None, Q.ATR_DERIVED,
            f"{sdesc} + 0.25*{atr_desc}", sa_placeholder, close, clamp=True),
        "entry_high": _classify(
            c.entry_zone_high, support + 0.75 * atr if have_sa else None, Q.ATR_DERIVED,
            f"{sdesc} + 0.75*{atr_desc}", sa_placeholder, close, clamp=True),
        "stop_loss": _classify(
            c.invalidation, support - 0.25 * atr if have_sa else None, Q.ATR_DERIVED,
            f"{sdesc} - 0.25*{atr_desc}", sa_placeholder, close, clamp=False),
        "target_1": _classify(
            s.resistance_scenario_1, resistance, Q.VERIFIED_STRUCTURE,
            f"20D high {resistance:.2f}" if resistance is not None else "", "resistance=close*1.05", close, clamp=False),
        "target_2": (
            _classify(
                s.resistance_scenario_2, resistance + 2 * atr if resistance is not None and atr is not None else None,
                Q.ATR_DERIVED, f"20D high + 2*{atr_desc}", "resistance=close*1.05 and/or ATR=close*2%", close,
                clamp=False)
            if s.resistance_scenario_2 is not None
            else LevelInput(price=None, quality=Q.UNAVAILABLE.value, provenance="not produced by scenario_engine")
        ),
    }


# ---- diagnostics (research only: never used to accept/reject) ---------------------------------


def _r(v: float | None, n: int = 2) -> float | None:
    return round(v, n) if v is not None else None


def diagnostics(c: CandidateResponse, levels: dict[str, LevelInput], generation_price: float | None) -> dict:
    t = c.technical
    lo, hi = levels["entry_low"].price, levels["entry_high"].price
    stop, t1, t2 = levels["stop_loss"].price, levels["target_1"].price, levels["target_2"].price
    ref = generation_price if generation_price is not None else c.price
    atr = t.atr_14

    def rr(entry: float | None, target: float | None) -> float | None:
        if entry is None or target is None or stop is None or entry <= stop:
            return None
        return round((target - entry) / (entry - stop), 2)

    mid = (lo + hi) / 2 if lo is not None and hi is not None else None
    position = None
    if lo is not None and hi is not None:
        position = "INSIDE_ZONE" if lo <= ref <= hi else ("ABOVE_ZONE" if ref > hi else "BELOW_ZONE")
    return {
        "note": "diagnostic only -- not used for acceptance, ranking or scoring",
        "reference_price": ref,
        "price_vs_zone": position,
        "zone_width_pct": _r((hi - lo) / ref * 100) if lo is not None and hi is not None else None,
        "reward_risk_t1_from_entry_high": rr(hi, t1),
        "reward_risk_t1_from_zone_mid": rr(mid, t1),
        "reward_risk_t1_from_reference": rr(ref, t1),
        "reward_risk_t2_from_entry_high": rr(hi, t2),
        "target_1_distance_pct": _r((t1 - ref) / ref * 100) if t1 is not None else None,
        "target_1_distance_atr": _r((t1 - ref) / atr) if t1 is not None and atr else None,
        "stop_distance_pct": _r((ref - stop) / ref * 100) if stop is not None else None,
        "stop_distance_atr": _r((ref - stop) / atr) if stop is not None and atr else None,
        "extension_above_ema20_atr": _r((ref - t.ema_20) / atr) if t.ema_20 is not None and atr else None,
        "trend_structure": t.trend_structure,
        "breakout_status": t.breakout_status,
        "pullback_status": t.pullback_status,
        "rsi_14": _r(t.rsi_14),
        "adx_14": _r(t.adx_14),
        "volume_ratio": _r(c.volume.volume_ratio),
        "relative_strength": c.relative_strength.label,
        "vs_nifty_pct_20d": _r(c.relative_strength.vs_nifty_pct_20d),
        "vs_sector_pct_20d": _r(c.relative_strength.vs_sector_pct_20d),
        "sector_strength": c.sector_context.sector_strength_label,
        "market_regime": c.sector_context.market_regime,
        "institutional_footprint_proxy": c.institutional_footprint.institutional_footprint_level,
        "fno_positioning_proxy": c.fno.positioning_proxy,
    }


# ---- generation price ---------------------------------------------------------------------------


async def fetch_generation_quotes(
    symbols: list[str], settings: Settings | None = None, now: dt.datetime | None = None,
    auth_status: str | None = None, live_reader=None,
) -> dict[str, GenerationQuote]:
    """Generation price from the shared LiveDataHub (the same
    subscribe -> settle -> read -> unsubscribe path Phase 6 collection uses;
    one process-wide WebSocket, reference counted, no REST polling).

    Why not REST /quotes: verified live on 2026-09-29, its `v.tt` is the
    session-date stamp (00:00 UTC, identical for every symbol), not a
    last-trade time, so a REST quote's freshness cannot be established.
    A hub tick's time is its RECEIPT time (FYERS lite mode sends none); it
    must be within live_data_stale_after_seconds during NSE hours
    (MARKET_OPEN_LIVE). Never fabricates a price."""
    from app.integrations.fyers.session import get_session_manager

    settings = settings or get_settings()
    now = now or dt.datetime.now(dt.UTC)
    if settings.use_mock_fyers:
        return {s: GenerationQuote(status=PRICE_MOCK, detail="USE_MOCK_FYERS=true") for s in symbols}
    if not (is_nse_trading_day(now.astimezone(IST).date()) and is_market_hours_ist(now)):
        return {s: GenerationQuote(status=PRICE_MARKET_CLOSED, detail="NSE is not in a live session") for s in symbols}
    auth = auth_status or get_session_manager(settings).status_code()
    if auth != "CONNECTED":
        return {s: GenerationQuote(status=PRICE_AUTH_REQUIRED, detail=f"FYERS session {auth}") for s in symbols}

    if live_reader is None:
        from app.services.candidate_live_subscription_service import collect_live_quotes_for_candidates

        live_reader = collect_live_quotes_for_candidates
    try:
        live = await live_reader(symbols, settings=settings)
    except FyersAuthRequiredError as exc:
        return {s: GenerationQuote(status=PRICE_AUTH_REQUIRED, detail=str(exc)[:200]) for s in symbols}
    read_at = dt.datetime.now(dt.UTC)

    out: dict[str, GenerationQuote] = {}
    for s in symbols:
        tick = live.get(s)
        if not tick or tick.get("ltp") is None or not tick.get("as_of"):
            out[s] = GenerationQuote(status=PRICE_UNAVAILABLE, detail="no live tick received in the settle window")
            continue
        at = dt.datetime.fromisoformat(str(tick["as_of"]))
        at = at.replace(tzinfo=dt.UTC) if at.tzinfo is None else at.astimezone(dt.UTC)
        status = classify_market_status(at, settings.live_data_stale_after_seconds, now_utc=read_at)
        out[s] = GenerationQuote(
            status=PRICE_OK if status == MARKET_STATUS_OPEN_LIVE else PRICE_STALE,
            price=float(tick["ltp"]), at=at, fetched_at=read_at, source=ObservationSource.TICK.value,
            market_status=status,
            detail="LiveDataHub tick, receipt-time basis" if status == MARKET_STATUS_OPEN_LIVE
            else f"tick {int((read_at - at).total_seconds())}s old ({status})",
        )
    return out


# ---- evaluation --------------------------------------------------------------------------------------


@dataclasses.dataclass
class CandidateEvaluation:
    symbol: str
    rank: int
    mtf_score: float
    eligible: bool
    rejection_reasons: list[str]
    levels: dict[str, dict]
    validation_notes: list[str]
    generation_price: dict
    diagnostics: dict
    would_create: dict | None = None
    creation_status: str | None = None
    suggestion_id: int | None = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _evidence_snapshot(c: CandidateResponse, rank: int, run_id: int | None, levels, quote: GenerationQuote,
                       diag: dict, research_context: dict | None) -> dict:
    """Only data that existed at generation time: the candidate as the
    scanner produced it, the generation quote, and (if supplied) research
    context captured at the same collection."""
    t = c.technical
    return {
        "snapshot_version": 2,
        "scanner_run_id": run_id,
        "mtf_rank": rank,
        "mtf_score": c.score,
        "signal_quality": c.signal_quality,
        "score_components": [
            {"name": sc.name, "weight": sc.weight, "points": sc.points_awarded, "available": sc.available}
            for sc in c.score_components
        ],
        "setup": {"type": c.setup.setup_type, "strength": c.setup.setup_strength},
        "scan_close_price": c.price,
        "technical": t.model_dump(mode="json"),
        "volume": {"volume_ratio": c.volume.volume_ratio, "relative_volume": c.volume.relative_volume,
                   "accumulation_score": c.volume.accumulation_score},
        "relative_strength": c.relative_strength.model_dump(mode="json"),
        "sector_context": {"sector": c.sector, "strength": c.sector_context.sector_strength_label,
                           "market_regime": c.sector_context.market_regime},
        "institutional_footprint_proxy": {"level": c.institutional_footprint.institutional_footprint_level,
                                          "score": c.institutional_footprint.institutional_footprint_score,
                                          # snapshot v2: evidence items, incl. the delivery proxy
                                          "evidence": [{"label": e.label, "detail": e.detail}
                                                       for e in c.institutional_footprint.evidence]},
        "fno": {"available": c.fno.is_available, "positioning_proxy": c.fno.positioning_proxy,
                "futures_oi_change_pct": c.fno.futures_oi_change_pct,
                "futures_price_change_pct": c.fno.futures_price_change_pct,
                "put_call_oi_ratio": c.fno.put_call_oi_ratio},
        "data_quality": c.data_quality.model_dump(mode="json"),
        "risks": list(c.risks),
        "levels": {k: v.model_dump() for k, v in levels.items()},
        "reward_risk": {k: diag[k] for k in ("reward_risk_t1_from_entry_high", "reward_risk_t1_from_zone_mid",
                                             "reward_risk_t1_from_reference", "reward_risk_t2_from_entry_high")},
        "generation_quote": {"price": quote.price, "last_trade_at": quote.at.isoformat() if quote.at else None,
                             "fetched_at": quote.fetched_at.isoformat() if quote.fetched_at else None,
                             "source": quote.source, "market_status": quote.market_status},
        "research_context": research_context,
    }


def _data_quality_label(c: CandidateResponse) -> str:
    if c.data_quality.stale_data:
        return "STALE"
    return f"DQ_SCORE_{c.data_quality.data_quality_score:.1f}"


def evaluate_candidate(
    c: CandidateResponse, rank: int, scanner_run_id: int | None, quote: GenerationQuote,
    settings: Settings | None = None, research_context: dict | None = None, extra_metadata: dict | None = None,
) -> tuple[CandidateEvaluation, SuggestionCreateRequest | None]:
    settings = settings or get_settings()
    levels = classify_levels(c)
    reasons: list[str] = []

    validation = validate_levels(
        Direction.LONG.value,
        {k: LevelSpec(price=v.price, quality=v.quality, provenance=v.provenance) for k, v in levels.items()},
    )
    reasons.extend(validation.reasons)
    if quote.status != PRICE_OK:
        reasons.append(f"generation price {quote.status}: {quote.detail}")
    if c.data_quality.stale_data:
        reasons.append(f"candidate has stale data: {c.data_quality.stale_data}")

    diag = diagnostics(c, levels, quote.price if quote.status == PRICE_OK else None)
    evaluation = CandidateEvaluation(
        symbol=c.symbol, rank=rank, mtf_score=c.score, eligible=not reasons, rejection_reasons=reasons,
        levels={k: v.model_dump() for k, v in levels.items()}, validation_notes=list(validation.notes),
        generation_price=dataclasses.asdict(quote), diagnostics=diag,
    )
    if reasons:
        return evaluation, None

    generated_at = quote.fetched_at
    request = SuggestionCreateRequest(
        scanner_type=ScannerType.MTF.value, market="NSE_EQ", symbol=c.symbol, instrument_type="EQUITY",
        direction=Direction.LONG.value, setup_type=c.setup.setup_type or "UNSPECIFIED",
        scanner_run_id=scanner_run_id, generated_at=generated_at,
        generation_market_price=quote.price, generation_price_source=quote.source,
        market_status=quote.market_status, data_quality=_data_quality_label(c),
        levels=levels, reference_entry_price=c.scenarios.preferred_entry,
        suggested_holding_period="1-4 weeks", score=c.score, confidence=None,
        evidence_snapshot=_evidence_snapshot(c, rank, scanner_run_id, levels, quote, diag, research_context),
        research_metadata={"adapter": "mtf_suggestion_adapter", "adapter_version": 1,
                           "scenario_engine_levels_reproduced": True, **(extra_metadata or {})},
    )
    entry_deadline, verified = nth_nse_session_after(generated_at.astimezone(IST).date(),
                                                      settings.suggestion_mtf_entry_window_sessions)
    evaluation.would_create = {
        "symbol": c.symbol, "direction": "LONG", "setup_type": request.setup_type,
        "generated_at": generated_at.isoformat(), "generation_market_price": quote.price,
        "generation_price_source": request.generation_price_source, "market_status": request.market_status,
        "entry_low": validation.levels["entry_low"], "entry_high": validation.levels["entry_high"],
        "target_1": validation.levels["target_1"], "target_2": validation.levels["target_2"],
        "stop_loss": validation.levels["stop_loss"], "entry_rule": "FRESH_TOUCH_AFTER_CREATION",
        "entry_deadline_session_date": entry_deadline.isoformat(), "session_calendar_verified": verified,
        "max_holding_sessions": settings.suggestion_mtf_max_holding_sessions,
    }
    return evaluation, request


def adapter_mode(settings: Settings, persist_override: bool | None = None) -> str:
    if not settings.enable_mtf_suggestion_adapter:
        return MODE_DISABLED
    if persist_override is not None:
        return MODE_PERSIST if persist_override else MODE_DRY_RUN
    return MODE_DRY_RUN if settings.mtf_suggestion_dry_run else MODE_PERSIST


_last_run: dict | None = None


def last_run() -> dict | None:
    return _last_run


async def run_mtf_adapter(
    db: AsyncSession | None,
    ranked_candidates: list[tuple[int, CandidateResponse]],
    scanner_run_id: int | None,
    settings: Settings | None = None,
    persist_override: bool | None = None,
    quotes: dict[str, GenerationQuote] | None = None,
    research_context: dict[str, dict] | None = None,
    extra_metadata: dict | None = None,
) -> dict:
    """ranked_candidates: (scanner rank, candidate) exactly as the scanner
    selected them. Candidates are read, never modified. extra_metadata
    (e.g. the collection run) is stored in each suggestion's research_metadata."""
    global _last_run
    settings = settings or get_settings()
    mode = adapter_mode(settings, persist_override)
    started = dt.datetime.now(dt.UTC)
    if mode == MODE_DISABLED:
        return {"mode": MODE_DISABLED, "evaluated": 0, "results": []}

    symbols = [c.symbol for _, c in ranked_candidates]
    if quotes is None:
        quotes = await fetch_generation_quotes(symbols, settings) if symbols else {}

    results: list[dict] = []
    for rank, candidate in ranked_candidates:
        quote = quotes.get(candidate.symbol) or GenerationQuote(status=PRICE_UNAVAILABLE, detail="no quote")
        evaluation, request = evaluate_candidate(
            candidate, rank, scanner_run_id, quote, settings, (research_context or {}).get(candidate.symbol),
            extra_metadata,
        )
        if mode == MODE_PERSIST and request is not None:
            if db is None:
                raise ValueError("persistence requires a database session")
            created = await svc.create_suggestion(db, request, settings)
            evaluation.creation_status = created.status.value
            evaluation.suggestion_id = created.suggestion_id
            if created.status not in (CreationStatus.CREATED, CreationStatus.DUPLICATE_OPEN):
                evaluation.eligible = False
                evaluation.rejection_reasons.extend(created.reasons)
        results.append(evaluation.as_dict())

    summary = {
        "mode": mode,
        "scanner_run_id": scanner_run_id,
        "started_at": started.isoformat(),
        "evaluated": len(results),
        "eligible": sum(1 for r in results if r["eligible"]),
        "rejected": sum(1 for r in results if not r["eligible"]),
        "persisted": sum(1 for r in results if r["creation_status"] == CreationStatus.CREATED.value),
        "results": results,
    }
    _last_run = summary
    logger.info("MTF suggestion adapter %s: run=%s evaluated=%d eligible=%d persisted=%d",
                mode, scanner_run_id, summary["evaluated"], summary["eligible"], summary["persisted"])
    return summary
