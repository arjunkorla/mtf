"""Scanner orchestration service -- implements POST /api/scanner/run
(section 21), the most important endpoint in the system.

Order of operations mirrors the architecture diagram in the spec:
  FYERS data -> validation -> normalization -> DB -> feature calculation ->
  institutional footprint -> ranking -> risk/position sizing -> (AI is a
  separate, later call, not made here) -> response.
"""

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_MAX_CANDIDATES, DEFAULT_MIN_CANDIDATES
from app.core.exceptions import (
    FyersApiError,
    FyersAuthError,
    FyersAuthRequiredError,
    FyersRateLimitError,
    InsufficientDataError,
    MtfError,
)
from app.data.universe import UniverseEntry, get_seed_universe
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import get_logger
from app.models.scanner_result import ScannerResult
from app.models.scanner_run import ScannerRun
from app.models.stock import Stock
from app.schemas.scanner import CandidateResponse, ScannerResultsResponse, ScannerRunRequest, ScannerRunResponse
from app.schemas.settings import ScannerSettings
from app.services.stock_service import CandidateRejected, build_candidate, get_nifty_candles, load_stock_context

logger = get_logger(__name__)


def _classify_error(exc: Exception) -> str:
    """Maps a per-symbol analysis failure to a specific rejection reason.

    Before this, every non-`CandidateRejected` failure -- a stale/invalid
    FYERS symbol, a rate limit, an upstream outage, and an actual bug in our
    own indicator math -- all landed in one "calculation_error" bucket. That
    made a delisted/renamed symbol (FYERS HTTP 422 "Invalid symbol provided",
    confirmed live for NSE:TATAMOTORS-EQ) indistinguishable from a real
    defect in this codebase. "calculation_error" is now reserved for
    exceptions we didn't already recognize -- i.e. an actual bug here, not an
    external data/API problem.
    """
    if isinstance(exc, FyersRateLimitError):
        return "api_rate_limited"
    if isinstance(exc, FyersAuthError):
        return "api_auth_error"
    if isinstance(exc, FyersApiError):
        if exc.status_code in (404, 422):
            return "invalid_symbol"
        if exc.status_code is not None and exc.status_code >= 500:
            return "api_unavailable"
        return "api_error"
    if isinstance(exc, InsufficientDataError):
        return "insufficient_data"
    return "calculation_error"


async def _ensure_stock_rows(db: AsyncSession, universe: list[UniverseEntry]) -> dict[str, Stock]:
    symbols = [e.symbol for e in universe]
    existing = (await db.execute(select(Stock).where(Stock.symbol.in_(symbols)))).scalars().all()
    by_symbol = {s.symbol: s for s in existing}

    for entry in universe:
        if entry.symbol in by_symbol:
            continue
        row = Stock(
            symbol=entry.symbol,
            exchange="NSE",
            company_name=entry.company_name,
            sector=entry.sector,
            is_fno=entry.is_fno,
            is_mtf_eligible=entry.is_mtf_eligible,
            is_liquid=True,
            is_active=True,
        )
        db.add(row)
        by_symbol[entry.symbol] = row

    await db.flush()
    return by_symbol


async def run_scanner(
    request: ScannerRunRequest,
    db: AsyncSession,
    settings: ScannerSettings,
) -> ScannerRunResponse:
    start = time.monotonic()
    universe = get_seed_universe()
    if request.symbols is not None:
        # ScannerRunRequest already validated these against the configured
        # universe and de-duplicated them, so this filter can't drop to an
        # empty list or admit an unconfigured symbol.
        wanted = set(request.symbols)
        universe = [entry for entry in universe if entry.symbol in wanted]

    run = ScannerRun(
        available_capital=request.available_capital,
        risk_percent=request.risk_percent,
        max_positions=request.max_positions,
        holding_period=request.holding_period,
        status="running",
    )
    db.add(run)
    await db.flush()

    client = FyersClient()
    candidates: list[CandidateResponse] = []
    rejection_summary: dict[str, int] = {}
    analyzed = 0

    try:
        nifty_candles = await get_nifty_candles(client)
        stock_rows = await _ensure_stock_rows(db, universe)

        for entry in universe:
            analyzed += 1
            try:
                context = await load_stock_context(client, db, entry, nifty_candles)
                candidate = await build_candidate(
                    client, entry, context, settings,
                    available_capital=request.available_capital,
                    risk_percent=request.risk_percent,
                )
                candidates.append(candidate)
            except FyersAuthRequiredError:
                # A dead session fails every remaining symbol the same way --
                # abort the run (-> 401 FYERS_AUTH_REQUIRED) instead of
                # returning a partial scan built from whichever symbols
                # happened to finish before the token expired.
                raise
            except CandidateRejected as exc:
                rejection_summary[exc.reason] = rejection_summary.get(exc.reason, 0) + 1
            except MtfError as exc:
                reason = _classify_error(exc)
                logger.error("Scanner failed to analyze %s (%s): %s", entry.symbol, reason, exc)
                rejection_summary[reason] = rejection_summary.get(reason, 0) + 1
            except Exception as exc:  # noqa: BLE001 -- one bad symbol must not fail the whole run
                reason = _classify_error(exc)
                logger.error("Scanner failed to analyze %s (%s): %s", entry.symbol, reason, exc)
                rejection_summary[reason] = rejection_summary.get(reason, 0) + 1

        # Explicit secondary key so exact score ties resolve the same way on
        # every run regardless of universe iteration order or how the loop
        # above is executed in the future (e.g. if per-symbol fetches are
        # ever parallelized) -- relying on sort() stability + insertion order
        # for tie-breaking is an implicit contract that would silently break
        # under either change. Symbol is ascending (alphabetical), unrelated
        # to score, so this never favors one candidate over another on
        # anything but the score itself.
        candidates.sort(key=lambda c: (-c.score, c.symbol))

        upper_bound = max(DEFAULT_MIN_CANDIDATES, min(request.max_positions, settings.max_candidates, DEFAULT_MAX_CANDIDATES))
        selected = candidates[:upper_bound]

        for rank, candidate in enumerate(selected, start=1):
            stock_row = stock_rows[candidate.symbol]
            db.add(
                ScannerResult(
                    run_id=run.id,
                    stock_id=stock_row.id,
                    symbol=candidate.symbol,
                    rank=rank,
                    score=candidate.score,
                    signal_quality=candidate.signal_quality,
                    payload=candidate.model_dump(mode="json"),
                )
            )

        run.status = "completed"
        run.stocks_analyzed = analyzed
        run.stocks_rejected = analyzed - len(candidates)
        run.stocks_selected = len(selected)
        run.execution_ms = int((time.monotonic() - start) * 1000)
        run.rejection_summary = rejection_summary
        import datetime as dt

        run.completed_at = dt.datetime.now(dt.UTC)

        await db.commit()

        logger.info(
            "Scanner run %s completed: analyzed=%d rejected=%d selected=%d in %dms",
            run.id, analyzed, run.stocks_rejected, len(selected), run.execution_ms,
        )

        return ScannerRunResponse(
            run_id=run.id,
            status=run.status,
            generated_at=run.completed_at,
            holding_period=request.holding_period,
            stocks_analyzed=analyzed,
            stocks_rejected=run.stocks_rejected,
            stocks_selected=len(selected),
            rejection_summary=rejection_summary,
            candidates=selected,
        )
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_message = str(exc)[:1000]
        await db.commit()
        logger.error("Scanner run %s failed: %s", run.id, exc)
        raise
    finally:
        await client.aclose()


async def get_scanner_results(db: AsyncSession, run_id: int | None = None) -> ScannerResultsResponse | None:
    if run_id is None:
        run = (
            await db.execute(select(ScannerRun).where(ScannerRun.status == "completed").order_by(ScannerRun.id.desc()))
        ).scalars().first()
    else:
        run = await db.get(ScannerRun, run_id)

    if run is None:
        return None

    results = (
        await db.execute(
            select(ScannerResult).where(ScannerResult.run_id == run.id).order_by(ScannerResult.rank)
        )
    ).scalars().all()

    candidates = [CandidateResponse.model_validate(r.payload) for r in results]

    return ScannerResultsResponse(
        run_id=run.id,
        status=run.status,
        generated_at=run.completed_at or run.started_at,
        candidates=candidates,
    )
