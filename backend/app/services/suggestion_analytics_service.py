"""Evidence dataset + descriptive analytics for tracked suggestions (Phase D).

Read-only. Reads PostgreSQL only -- never FYERS.

Features come ONLY from the immutable generation-time evidence snapshot /
research context captured at generation (never back-filled; a field that
was not captured is None). Outcome fields come from the tracked lifecycle.

Descriptive statistics only: counts, rates with 95% Wilson intervals and
medians, always with their sample sizes. Segment buckets are fixed-width
DISPLAY groupings, not thresholds, and nothing here feeds scoring.
"""

import datetime as dt
import statistics

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.suggestion_constants import OPEN_STATUSES, SuggestionOutcome, SuggestionStatus
from app.models.mtf_collection_run import MtfCollectionRun
from app.models.scanner_run import ScannerRun
from app.models.trade_suggestion import TradeSuggestion
from app.services import suggestion_service as svc
from app.services.market_data_service import is_market_hours_ist

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
O = SuggestionOutcome
QUALITY_ABBR = {"VERIFIED_STRUCTURE": "VS", "ATR_DERIVED": "ATR", "FALLBACK": "FB", "UNAVAILABLE": "NA"}


def _get(d, *path):
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _pct(a: float | None, b: float | None) -> float | None:
    return round((a - b) / b * 100, 3) if a is not None and b else None


def _atr_units(a: float | None, b: float | None, atr: float | None) -> float | None:
    return round((a - b) / atr, 3) if a is not None and b is not None and atr else None


def _rel(price: float | None, ref: float | None) -> str | None:
    if price is None or ref is None:
        return None
    return "ABOVE" if price > ref else ("BELOW" if price < ref else "AT")


def scan_candle_basis(row: TradeSuggestion, scan_times: dict[int, dt.datetime]) -> str:
    """Whether the scanner run that produced the levels could have included a
    forming daily candle. Derived from facts known at generation time."""
    recorded = _get(row.research_metadata, "scan_candle_basis")
    if recorded:
        return recorded
    t = scan_times.get(row.scanner_run_id) if row.scanner_run_id else None
    if t is None:
        return "UNKNOWN"
    t = svc._aware(t)
    return "INCLUDED_FORMING_DAILY_CANDLE" if is_market_hours_ist(t) else "COMPLETED_DAILY_CANDLES"


def entry_classification(row: TradeSuggestion) -> str:
    if row.entry_triggered_at is not None:
        return "IMMEDIATE_ENTRY" if row.generation_price_zone_position == "INSIDE" else "PULLBACK_ENTRY"
    if row.status == SuggestionStatus.NO_ENTRY.value:
        return "NO_ENTRY"
    if row.status == SuggestionStatus.INVALIDATED.value:
        return "INVALIDATED_BEFORE_ENTRY"
    if row.status == SuggestionStatus.WAITING_ENTRY.value:
        return "WAITING_ENTRY"
    return "NOT_ENTERED_OTHER"


def _delivery(snapshot: dict, research: dict | None) -> str | None:
    for item in _get(snapshot, "institutional_footprint_proxy", "evidence") or []:
        if isinstance(item, dict) and item.get("label") == "Delivery behaviour proxy":
            return item.get("detail")
    return _get(research, "delivery_state")


def build_row(row: TradeSuggestion, scan_times: dict[int, dt.datetime] | None = None) -> dict:
    snap = row.evidence_snapshot or {}
    research = snap.get("research_context") or None
    tech = snap.get("technical") or {}
    lq = row.level_quality or {}

    gen = _num(row.generation_market_price)
    lo, hi, t1, t2, stop = (_num(row.entry_low), _num(row.entry_high), _num(row.target_1),
                            _num(row.target_2), _num(row.stop_loss))
    atr = _num(tech.get("atr_14"))
    entry = _num(row.entry_triggered_price)
    mfp, mapx = _num(row.max_favorable_price), _num(row.max_adverse_price)
    adverse_pre_t1 = _num(row.max_adverse_price_before_target_1)

    if gen is None or lo is None or hi is None:
        dist_entry = None
    elif lo <= gen <= hi:
        dist_entry = 0.0
    else:
        dist_entry = _pct(hi if gen > hi else lo, gen)

    ema20, ema50, ema200 = _num(tech.get("ema_20")), _num(tech.get("ema_50")), _num(tech.get("ema_200"))
    generated_at = svc._aware(row.generated_at)
    closed_at = svc._aware(row.closed_at)

    def rr(e):
        return round((t1 - e) / (e - stop), 3) if e is not None and t1 is not None and stop is not None and e > stop else None

    return {
        # identity / generation
        "id": row.id, "symbol": row.symbol, "scanner_type": row.scanner_type, "setup_type": row.setup_type,
        "generated_at": generated_at, "generated_at_ist": generated_at.astimezone(IST).isoformat() if generated_at else None,
        "generation_session_date": row.generation_session_date,
        "scanner_run_id": row.scanner_run_id,
        "collection_run_id": _get(row.research_metadata, "collection_run_id"),
        "scan_candle_basis": scan_candle_basis(row, scan_times or {}),
        "snapshot_version": snap.get("snapshot_version"),
        "mtf_rank": snap.get("mtf_rank"), "mtf_score": _num(row.score), "signal_quality": snap.get("signal_quality"),
        # technical (generation time)
        "trend_structure": tech.get("trend_structure"), "breakout_status": tech.get("breakout_status"),
        "pullback_status": tech.get("pullback_status"),
        "rsi_14": _num(tech.get("rsi_14")), "adx_14": _num(tech.get("adx_14")), "atr_14": atr,
        "atr_pct": round(atr / gen * 100, 3) if atr and gen else None,
        "price_vs_ema20": _rel(gen, ema20), "price_vs_ema50": _rel(gen, ema50), "price_vs_ema200": _rel(gen, ema200),
        "ema20_above_ema50": (ema20 > ema50) if ema20 is not None and ema50 is not None else None,
        "ema50_above_ema200": (ema50 > ema200) if ema50 is not None and ema200 is not None else None,
        "volume_ratio": _num(_get(snap, "volume", "volume_ratio")),
        # strength / context
        "stock_return_5d": _num(_get(research, "stock_return_5d")),
        "stock_return_20d": _num(_get(research, "stock_return_20d")),
        "relative_strength": _get(snap, "relative_strength", "label"),
        "vs_nifty_pct_20d": _num(_get(snap, "relative_strength", "vs_nifty_pct_20d")),
        "vs_sector_pct_20d": _num(_get(snap, "relative_strength", "vs_sector_pct_20d")),
        "sector": _get(snap, "sector_context", "sector"),
        "sector_strength": _get(snap, "sector_context", "strength"),
        "sector_participation": _get(research, "sector_participation"),
        "market_regime": _get(snap, "sector_context", "market_regime"),
        "institutional_footprint_proxy": _get(snap, "institutional_footprint_proxy", "level"),
        "delivery_evidence": _delivery(snap, research),
        "fno_positioning_proxy": _get(snap, "fno", "positioning_proxy"),
        "futures_price_change_pct": _num(_get(snap, "fno", "futures_price_change_pct")),
        "futures_oi_change_pct": _num(_get(snap, "fno", "futures_oi_change_pct")),
        "research_confirmation_score": _num(_get(research, "research_confirmation_score")),
        "research_status": _get(research, "research_status"),
        "research_divergence": _get(research, "divergence"),
        "india_vix": _num(_get(research, "india_vix")), "vix_regime": _get(research, "vix_regime"),
        "global_risk_sentiment": _get(research, "global_risk_sentiment"), "nifty_regime": _get(research, "nifty_regime"),
        "research_context_source": _get(research, "source"),
        # levels
        "generation_market_price": gen, "generation_price_source": row.generation_price_source,
        "generation_price_zone_position": row.generation_price_zone_position,
        "entry_low": lo, "entry_high": hi, "stop_loss": stop, "target_1": t1, "target_2": t2,
        "distance_to_entry_pct": dist_entry,
        "stop_distance_pct": _pct(gen, stop) if gen and stop else None,
        "target_1_distance_pct": _pct(t1, gen), "target_2_distance_pct": _pct(t2, gen),
        "stop_distance_atr": _atr_units(gen, stop, atr), "target_1_distance_atr": _atr_units(t1, gen, atr),
        "target_2_distance_atr": _atr_units(t2, gen, atr),
        "nominal_rr_t1_from_entry_high": rr(hi), "nominal_rr_t1_from_generation": rr(gen),
        "level_quality": {k: _get(v, "quality") for k, v in lq.items()},
        "level_provenance": {k: _get(v, "provenance") for k, v in lq.items()},
        "level_quality_signature": "|".join(
            f"{k}:{QUALITY_ABBR.get(_get(lq, k, 'quality'), '-')}" for k in ("entry_low", "entry_high", "target_1", "stop_loss")
        ),
        # lifecycle / outcome
        "status": row.status, "outcome": row.outcome, "is_open": row.status in {s.value for s in OPEN_STATUSES},
        "entry_classification": entry_classification(row),
        "entry_triggered": row.entry_triggered_at is not None, "entry_price": entry,
        "entry_time": svc._aware(row.entry_triggered_at), "target_1_time": svc._aware(row.target_1_hit_at),
        "target_2_time": svc._aware(row.target_2_hit_at), "stop_time": svc._aware(row.stop_hit_at),
        "expiry_time": closed_at if row.status == SuggestionStatus.EXPIRED.value else None,
        "closed_at": closed_at, "ambiguous_bar": bool(row.ambiguous_bar),
        "mfe_price": mfp, "mae_price": mapx,
        "mfe_pct": _num(row.max_favorable_excursion), "mae_pct": _num(row.max_adverse_excursion),
        "mfe_atr": _atr_units(mfp, entry, atr), "mae_atr": _atr_units(mapx, entry, atr),
        "mae_before_target_1_atr": _atr_units(adverse_pre_t1, entry, atr),
        "target_1_distance_atr_from_entry": _atr_units(t1, entry, atr),
        "target_2_distance_atr_from_entry": _atr_units(t2, entry, atr),
        "stop_distance_atr_from_entry": _atr_units(entry, stop, atr),
        "realized_or_marked_return_pct": _num(row.realized_or_marked_return_pct),
        "return_is_realized": bool(row.return_is_realized),
        "minutes_to_entry": svc._minutes(row.generated_at, row.entry_triggered_at),
        "minutes_entry_to_mfe": svc._minutes(row.entry_triggered_at, row.max_favorable_at),
        "minutes_entry_to_target_1": svc._minutes(row.entry_triggered_at, row.target_1_hit_at),
        "minutes_entry_to_target_2": svc._minutes(row.entry_triggered_at, row.target_2_hit_at),
        "minutes_entry_to_stop": svc._minutes(row.entry_triggered_at, row.stop_hit_at),
        "sessions_to_entry": svc._sessions_between(row.generated_at, row.entry_triggered_at),
        "sessions_entry_to_mfe": svc._sessions_between(row.entry_triggered_at, row.max_favorable_at),
        "sessions_entry_to_target_1": svc._sessions_between(row.entry_triggered_at, row.target_1_hit_at),
        "sessions_entry_to_target_2": svc._sessions_between(row.entry_triggered_at, row.target_2_hit_at),
        "sessions_entry_to_stop": svc._sessions_between(row.entry_triggered_at, row.stop_hit_at),
        "excursion_timing_available": row.max_favorable_at is not None,
        "session_calendar_verified": bool(row.session_calendar_verified),
        "tracking_status": row.tracking_status, "reconciled_through": svc._aware(row.reconciled_through),
    }


async def _scan_times(db: AsyncSession, rows: list[TradeSuggestion]) -> dict[int, dt.datetime]:
    ids = {r.scanner_run_id for r in rows if r.scanner_run_id}
    if not ids:
        return {}
    runs = (await db.execute(select(ScannerRun.id, ScannerRun.completed_at).where(ScannerRun.id.in_(ids)))).all()
    return {rid: t for rid, t in runs if t is not None}


async def dataset(db: AsyncSession, filters: svc.SuggestionFilters, limit: int = 100000, offset: int = 0) -> tuple[list[dict], int]:
    rows, total = await svc.query_suggestions(db, filters, limit, offset)
    times = await _scan_times(db, rows)
    return [build_row(r, times) for r in rows], total


# ---- statistics --------------------------------------------------------------------------------

COMPLETED = svc.COMPLETED_TRADE_OUTCOMES


def _median(values) -> float | None:
    v = [x for x in values if x is not None]
    return round(statistics.median(v), 3) if v else None


def _rate(k: int, n: int) -> dict:
    return {"count": k, "n": n, "pct": round(k / n * 100, 2) if n else None, "ci95_pct": svc.wilson_interval(k, n)}


def outcome_stats(rows: list[dict]) -> dict:
    triggered = [r for r in rows if r["entry_triggered"]]
    completed = [r for r in triggered if r["outcome"] in COMPLETED]
    entry_resolved = [r for r in rows if r["entry_triggered"] or r["status"] in ("NO_ENTRY", "INVALIDATED")]
    wins = sum(r["outcome"] in svc.WIN_OUTCOMES for r in completed)
    return {
        "suggestions": len(rows),
        "entry_resolved": len(entry_resolved), "triggered": len(triggered), "completed_trades": len(completed),
        "trigger_rate": _rate(len(triggered), len(entry_resolved)),
        "target_1_hit_rate": _rate(sum(r["target_1_time"] is not None for r in completed), len(completed)),
        "target_2_hit_rate": _rate(sum(r["target_2_time"] is not None for r in completed), len(completed)),
        "stop_rate": _rate(sum(r["stop_time"] is not None for r in completed), len(completed)),
        "failed_stop_rate": _rate(sum(r["outcome"] == O.FAILED_STOP.value for r in completed), len(completed)),
        "partial_success_rate": _rate(sum(r["outcome"] == O.PARTIAL_SUCCESS.value for r in completed), len(completed)),
        "win_rate": _rate(wins, len(completed)),
        "expired_rate": _rate(sum(r["outcome"] == O.EXPIRED.value for r in completed), len(completed)),
        "median_mfe_pct_triggered": _median(r["mfe_pct"] for r in triggered),
        "median_mae_pct_triggered": _median(r["mae_pct"] for r in triggered),
        "median_mfe_atr_completed": _median(r["mfe_atr"] for r in completed),
        "median_mae_atr_completed": _median(r["mae_atr"] for r in completed),
    }


def analytics(rows: list[dict], collection_runs: list[MtfCollectionRun]) -> dict:
    by_status = {s.value: 0 for s in SuggestionStatus}
    by_outcome = {o.value: 0 for o in SuggestionOutcome}
    by_entry_class: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
        by_entry_class[r["entry_classification"]] = by_entry_class.get(r["entry_classification"], 0) + 1

    triggered = [r for r in rows if r["entry_triggered"]]
    completed = [r for r in triggered if r["outcome"] in COMPLETED]
    t1_rows = [r for r in triggered if r["target_1_time"] is not None]
    stop_rows = [r for r in triggered if r["stop_time"] is not None]

    gen_runs = [c for c in collection_runs if c.stage == "GENERATE"]
    reasons: dict[str, int] = {}
    for run in gen_runs:
        for res in (run.summary or {}).get("results", []):
            for reason in res.get("rejection_reasons") or []:
                key = reason_category(reason)
                reasons[key] = reasons.get(key, 0) + 1

    feasible = [r for r in triggered if r["mfe_atr"] is not None and r["target_1_distance_atr_from_entry"] is not None]
    return {
        "note": "Descriptive statistics only -- not evidence of profitability. Always read with the sample sizes.",
        "collection": {
            "generate_runs": len(gen_runs),
            "generate_runs_by_status": _count(c.status for c in gen_runs),
            "scan_runs_by_status": _count(c.status for c in collection_runs if c.stage == "SCAN"),
            "candidates_evaluated": sum(c.candidates or 0 for c in gen_runs),
            "eligible": sum(c.eligible or 0 for c in gen_runs),
            "rejected": sum(c.rejected or 0 for c in gen_runs),
            "persisted": sum(c.persisted or 0 for c in gen_runs),
            "rejection_reasons": reasons,
            "note": "Counts only cover scheduled/operator collection runs; the Phase C controlled test "
                    "(scanner run 172) predates the collection ledger.",
        },
        "suggestions_generated": len(rows),
        "by_status": by_status, "by_outcome": by_outcome,
        "waiting_entry": by_status[SuggestionStatus.WAITING_ENTRY.value],
        "active": by_status[SuggestionStatus.ACTIVE.value] + by_status[SuggestionStatus.TARGET_1_HIT.value],
        "completed_trades": len(completed),
        "entry_classification": by_entry_class,
        **{k: v for k, v in outcome_stats(rows).items() if k not in ("suggestions",)},
        "median_minutes_to_entry": _median(r["minutes_to_entry"] for r in triggered),
        "median_minutes_entry_to_target_1": _median(r["minutes_entry_to_target_1"] for r in t1_rows),
        "median_minutes_entry_to_stop": _median(r["minutes_entry_to_stop"] for r in stop_rows),
        "median_minutes_entry_to_mfe": _median(r["minutes_entry_to_mfe"] for r in triggered),
        "target_feasibility": {
            "median_target_1_distance_atr_from_entry": _median(r["target_1_distance_atr_from_entry"] for r in triggered),
            "median_target_2_distance_atr_from_entry": _median(r["target_2_distance_atr_from_entry"] for r in triggered),
            "median_mfe_atr_triggered": _median(r["mfe_atr"] for r in triggered),
            "median_mfe_atr_completed": _median(r["mfe_atr"] for r in completed),
            "mfe_reached_target_1_distance": _rate(
                sum(r["mfe_atr"] >= r["target_1_distance_atr_from_entry"] for r in feasible), len(feasible)),
            "note": "Open trades are still accumulating MFE; use the *_completed figures for settled evidence.",
        },
        "stop_feasibility": {
            "median_stop_distance_atr_from_entry": _median(r["stop_distance_atr_from_entry"] for r in triggered),
            "median_mae_atr_triggered": _median(r["mae_atr"] for r in triggered),
            "median_mae_before_target_1_atr": _median(r["mae_before_target_1_atr"] for r in t1_rows),
            "stopped_trades": len(stop_rows),
            "note": "mae_before_target_1 is a bar-resolution lower bound (excludes the target-1 bar).",
        },
        "sample_size": len(completed),
    }


def reason_category(reason: str) -> str:
    r = reason.lower()
    if r.startswith("generation price"):
        return reason.split(":")[0]
    for level in ("entry_low", "entry_high", "target_1", "target_2", "stop_loss"):
        if r.startswith(level) and "quality" in r:
            return f"{level} {reason.split('quality ')[1].split(' ')[0]}"
    if "must be" in r:
        return "invalid geometry: " + reason.split(" ")[1] + " " + " ".join(reason.split(" ")[2:5])
    if "stale data" in r:
        return "stale candidate data"
    return reason[:80]


def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# ---- segments ----------------------------------------------------------------------------------


def _bucket(value, width: float, fmt: str = "{:g}") -> str:
    if value is None:
        return "UNAVAILABLE"
    lo = (value // width) * width
    return f"{fmt.format(lo)}-{fmt.format(lo + width)}"


def _rank_bucket(rank) -> str:
    if rank is None:
        return "UNAVAILABLE"
    return "1-3" if rank <= 3 else "4-6" if rank <= 6 else "7-10" if rank <= 10 else "11+"


SEGMENTS = {
    "mtf_score_bucket": lambda r: _bucket(r["mtf_score"], 10),
    "rank_bucket": lambda r: _rank_bucket(r["mtf_rank"]),
    "trend": lambda r: r["trend_structure"] or "UNAVAILABLE",
    "rsi_bucket": lambda r: _bucket(r["rsi_14"], 10),
    "adx_bucket": lambda r: _bucket(r["adx_14"], 10),
    "volume_ratio_bucket": lambda r: _bucket(r["volume_ratio"], 0.5),
    "sector_participation": lambda r: r["sector_participation"] or "UNAVAILABLE",
    "relative_strength": lambda r: r["relative_strength"] or "UNAVAILABLE",
    "research_confirmation_bucket": lambda r: _bucket(r["research_confirmation_score"], 10),
    "research_status": lambda r: r["research_status"] or "UNAVAILABLE",
    "macro_regime": lambda r: r["global_risk_sentiment"] or "UNAVAILABLE",
    "market_regime": lambda r: r["market_regime"] or "UNAVAILABLE",
    "vix_regime": lambda r: r["vix_regime"] or "UNAVAILABLE",
    "fno_positioning": lambda r: r["fno_positioning_proxy"] or "UNAVAILABLE",
    "institutional_footprint": lambda r: r["institutional_footprint_proxy"] or "UNAVAILABLE",
    "level_provenance": lambda r: r["level_quality_signature"],
    "entry_classification": lambda r: r["entry_classification"],
    "scan_candle_basis": lambda r: r["scan_candle_basis"],
}


def segments(rows: list[dict], by: str) -> dict:
    if by not in SEGMENTS:
        raise KeyError(by)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(SEGMENTS[by](r), []).append(r)
    out = []
    for key in sorted(groups):
        g = groups[key]
        stats = outcome_stats(g)
        out.append({
            "segment": key, **stats,
            "outcomes": _count(r["outcome"] for r in g),
            "no_entry": sum(r["status"] == "NO_ENTRY" for r in g),
            "invalidated_before_entry": sum(r["status"] == "INVALIDATED" for r in g),
        })
    return {
        "by": by, "groups": out,
        "note": "Fixed-width display buckets, not optimized thresholds. Small groups are not conclusive; "
                "nothing here feeds scoring.",
    }
