"""MTF daily evidence collection (Phase D). OFF unless
ENABLE_MTF_DAILY_COLLECTION=true; dry-run unless
MTF_DAILY_COLLECTION_DRY_RUN=false. Never places orders.

Two stages per NSE session, each at most once (UNIQUE dedup key):

  SCAN      after the close of session D (default 16:00 IST, allowed until
            09:00 IST of the next session): ONE run of the unmodified MTF
            scanner. At that time every daily candle is COMPLETE -- the
            Phase D audit showed that a scan during market hours includes
            the forming candle, which roughly halves volume_ratio and changed
            scores (up to 17 points), ranks and the adapter's level validity
            for half the universe. Status COMPLETED or NO_CANDIDATES.

  GENERATE  at a fixed slot of the next session T (default 09:30-10:30 IST):
            the Phase C adapter over the SCAN(D = previous session)'s
            selected candidates, with a live LiveDataHub generation price.
            Persists (unless dry-run) only candidates that pass Phase A
            validation. Status COMPLETED, NO_VALID_SETUP (a valid result),
            SKIPPED_NO_SCAN or SKIPPED_MISSED_WINDOW.

The tracker picks up persisted suggestions on its next cycle (it loads open
suggestions from PostgreSQL). Auth not CONNECTED -> nothing is recorded and
the stage retries on the next poll inside its window. A run interrupted by a
restart is marked FAILED_INTERRUPTED and may be retried (bounded attempts);
suggestion persistence is itself idempotent (open dedup key).
"""

import asyncio
import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings, get_settings
from app.core.exceptions import FyersAuthRequiredError
from app.data.nse_holidays import is_nse_trading_day
from app.logging_config import get_logger
from app.models.mtf_collection_run import MtfCollectionRun

logger = get_logger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
STAGE_SCAN = "SCAN"
STAGE_GENERATE = "GENERATE"

RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
NO_CANDIDATES = "NO_CANDIDATES"
NO_VALID_SETUP = "NO_VALID_SETUP"
FAILED = "FAILED"
FAILED_INTERRUPTED = "FAILED_INTERRUPTED"
SKIPPED_NO_SCAN = "SKIPPED_NO_SCAN"
SKIPPED_MISSED_WINDOW = "SKIPPED_MISSED_WINDOW"
RETRYABLE = frozenset({FAILED, FAILED_INTERRUPTED})

PRE_OPEN = dt.time(9, 0)


def _t(value: str) -> dt.time:
    h, m = value.split(":")
    return dt.time(int(h), int(m))


def _at(d: dt.date, t: dt.time) -> dt.datetime:
    return dt.datetime.combine(d, t, tzinfo=IST).astimezone(dt.UTC)


def previous_trading_day(d: dt.date) -> dt.date:
    d -= dt.timedelta(days=1)
    while not is_nse_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(d: dt.date) -> dt.date:
    d += dt.timedelta(days=1)
    while not is_nse_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def dedup_key(stage: str, session_date: dt.date, dry_run: bool) -> str:
    return f"{stage}|{session_date.isoformat()}|{'DRY' if dry_run else 'LIVE'}"


def scan_session_due(now: dt.datetime, settings: Settings) -> dt.date | None:
    """The completed session a SCAN may run for at `now`, or None. Only
    between the scan time of session D and the pre-open of the next
    session, i.e. never while any daily candle can be forming."""
    ist = now.astimezone(IST)
    today = ist.date()
    scan_time = _t(settings.mtf_daily_scan_time_ist)
    if is_nse_trading_day(today) and ist.time() >= scan_time:
        d = today
    else:
        d = previous_trading_day(today)
    if now < _at(d, scan_time) or now >= _at(next_trading_day(d), PRE_OPEN):
        return None
    return d


def generate_window(now: dt.datetime, settings: Settings) -> tuple[dt.date | None, bool]:
    """(generation session, window_open). window_open False with a date
    means the fixed slot has passed for that session."""
    ist = now.astimezone(IST)
    today = ist.date()
    if not is_nse_trading_day(today):
        return None, False
    start, end = _at(today, _t(settings.mtf_daily_generate_time_ist)), _at(today, _t(settings.mtf_daily_generate_deadline_ist))
    if now < start:
        return None, False
    return today, now < end


class MtfDailyCollector:
    def __init__(self, settings: Settings | None = None, session_factory=None, clock=None, auth_status=None,
                 scanner=None, adapter=None, redis_getter=None):
        self.settings = settings or get_settings()
        self._session_factory = session_factory
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._auth_status = auth_status
        self._scanner = scanner  # test hook: async (db, request) -> ScannerRunResponse
        self._adapter = adapter  # test hook: same signature as run_mtf_adapter
        self._redis_getter = redis_getter
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self._lock = asyncio.Lock()
        self.state = "DISABLED" if not self.settings.enable_mtf_daily_collection else "NOT_STARTED"
        self.last_tick: dict = {}

    @property
    def dry_run(self) -> bool:
        return self.settings.mtf_daily_collection_dry_run

    def _session(self):
        if self._session_factory is None:
            from app.db.base import AsyncSessionLocal

            self._session_factory = AsyncSessionLocal
        return self._session_factory()

    def _auth(self) -> str:
        if self.settings.use_mock_fyers:
            return "MOCK"
        if self._auth_status is not None:
            return self._auth_status()
        from app.integrations.fyers.session import get_session_manager

        return get_session_manager(self.settings).status_code()

    # -- lifecycle ------------------------------------------------------------------------

    async def start(self) -> bool:
        if not self.settings.enable_mtf_daily_collection:
            self.state = "DISABLED"
            logger.info("MTF daily collection disabled (ENABLE_MTF_DAILY_COLLECTION=false)")
            return False
        await self.recover_interrupted()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="mtf-daily-collection")
        self.state = "RUNNING"
        logger.info("MTF daily collection started (dry_run=%s)", self.dry_run)
        return True

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self.state == "RUNNING":
            self.state = "STOPPED"

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 -- never kill the loop
                logger.exception("MTF daily collection tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.mtf_daily_collection_poll_seconds)
                return
            except TimeoutError:
                pass

    async def recover_interrupted(self) -> int:
        """Rows left RUNNING by a crash/restart become FAILED_INTERRUPTED and
        release their dedup key (so a bounded retry is possible)."""
        async with self._session() as db:
            rows = (await db.execute(select(MtfCollectionRun).where(MtfCollectionRun.status == RUNNING))).scalars().all()
            for row in rows:
                row.status, row.dedup_key = FAILED_INTERRUPTED, None
                row.reason = "process stopped while the stage was running"
                row.completed_at = self._clock()
            await db.commit()
        return len(rows)

    # -- scheduling ---------------------------------------------------------------------------

    async def tick(self) -> dict:
        async with self._lock:
            now = self._clock()
            out: dict = {"at": now.isoformat()}
            scan_d = scan_session_due(now, self.settings)
            if scan_d is not None:
                out["scan"] = await self._maybe(STAGE_SCAN, scan_d, now)
            gen_d, gen_open = generate_window(now, self.settings)
            if gen_d is not None:
                if gen_open:
                    out["generate"] = await self._maybe(STAGE_GENERATE, gen_d, now)
                else:
                    out["generate"] = await self._record_missed(gen_d, now)
            self.last_tick = out
            return out

    async def _existing(self, db, stage: str, d: dt.date) -> tuple[MtfCollectionRun | None, int]:
        key = dedup_key(stage, d, self.dry_run)
        done = (await db.execute(select(MtfCollectionRun).where(MtfCollectionRun.dedup_key == key))).scalar_one_or_none()
        attempts = (await db.execute(select(func.count(MtfCollectionRun.id)).where(
            MtfCollectionRun.stage == stage, MtfCollectionRun.session_date == d,
            MtfCollectionRun.dry_run == self.dry_run, MtfCollectionRun.forced.is_(False),
        ))).scalar() or 0
        return done, attempts

    async def _maybe(self, stage: str, d: dt.date, now: dt.datetime) -> dict:
        async with self._session() as db:
            done, attempts = await self._existing(db, stage, d)
        if done is not None:
            return {"status": "ALREADY_DONE", "run_id": done.id, "run_status": done.status}
        if attempts >= self.settings.mtf_daily_max_attempts:
            return {"status": "ATTEMPTS_EXHAUSTED", "attempts": attempts}
        auth = self._auth()
        if auth != "CONNECTED":
            return {"status": "WAITING_FOR_AUTH", "fyers": auth}  # nothing recorded; retried next poll
        runner = self.run_scan if stage == STAGE_SCAN else self.run_generate
        return await runner(d)

    async def _record_missed(self, d: dt.date, now: dt.datetime) -> dict:
        async with self._session() as db:
            done, _ = await self._existing(db, STAGE_GENERATE, d)
            if done is not None:
                return {"status": "ALREADY_DONE", "run_id": done.id, "run_status": done.status}
            row = self._new_row(STAGE_GENERATE, d, forced=False)
            row.status, row.completed_at = SKIPPED_MISSED_WINDOW, now
            row.reason = f"generation slot {self.settings.mtf_daily_generate_time_ist}-" \
                         f"{self.settings.mtf_daily_generate_deadline_ist} IST passed without a run"
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return {"status": "ALREADY_DONE"}
            return {"status": SKIPPED_MISSED_WINDOW, "run_id": row.id}

    def _new_row(self, stage: str, d: dt.date, forced: bool) -> MtfCollectionRun:
        return MtfCollectionRun(
            stage=stage, session_date=d, dry_run=self.dry_run, forced=forced,
            dedup_key=None if forced else dedup_key(stage, d, self.dry_run),
            status=RUNNING, started_at=self._clock(), summary={},
        )

    async def _claim(self, stage: str, d: dt.date, forced: bool) -> MtfCollectionRun | None:
        async with self._session() as db:
            row = self._new_row(stage, d, forced)
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:  # another process/restart already claimed it
                await db.rollback()
                return None
            return row

    async def _finish(self, row_id: int, **fields) -> None:
        async with self._session() as db:
            row = await db.get(MtfCollectionRun, row_id)
            for k, v in fields.items():
                setattr(row, k, v)
            if fields.get("status") in RETRYABLE:
                row.dedup_key = None  # a failed stage may be retried (bounded)
            row.completed_at = self._clock()
            await db.commit()

    # -- stages ------------------------------------------------------------------------------------

    async def run_scan(self, d: dt.date, forced: bool = False) -> dict:
        from app.integrations.fyers.request_control import RequestPriority, fyers_priority
        from app.schemas.scanner import ScannerRunRequest

        due = scan_session_due(self._clock(), self.settings)
        if due != d:
            # No override, not even --force: outside the post-close window a
            # daily candle may be forming (or `d` is not the latest completed
            # session), which is exactly the contamination the audit found.
            return {"status": "REFUSED_OUTSIDE_COMPLETED_CANDLE_WINDOW", "requested_session": d.isoformat(),
                    "scannable_session_now": due.isoformat() if due else None}
        row = await self._claim(STAGE_SCAN, d, forced)
        if row is None:
            return {"status": "ALREADY_DONE"}
        request = ScannerRunRequest(
            available_capital=self.settings.mtf_daily_scan_capital,
            risk_percent=self.settings.mtf_daily_scan_risk_percent,
            max_positions=self.settings.mtf_daily_scan_max_positions,
        )
        try:
            with fyers_priority(RequestPriority.BACKGROUND):
                async with self._session() as db:
                    result = await self._run_scanner(db, request)
        except FyersAuthRequiredError as exc:
            await self._finish(row.id, status=FAILED, reason=f"FYERS auth required: {str(exc)[:200]}")
            return {"status": FAILED, "run_id": row.id}
        except Exception as exc:  # noqa: BLE001
            logger.exception("MTF daily SCAN failed")
            await self._finish(row.id, status=FAILED, reason=f"{type(exc).__name__}: {str(exc)[:300]}")
            return {"status": FAILED, "run_id": row.id}

        status = COMPLETED if result.candidates else NO_CANDIDATES
        await self._finish(
            row.id, status=status, scanner_run_id=result.run_id, candidates=len(result.candidates),
            summary={
                "candle_basis": "COMPLETED_DAILY_CANDLES",
                "scanner_generated_at": result.generated_at.isoformat(),
                "stocks_analyzed": result.stocks_analyzed, "stocks_rejected": result.stocks_rejected,
                "rejection_summary": result.rejection_summary,
                "selected": [{"rank": i, "symbol": c.symbol, "score": c.score}
                             for i, c in enumerate(result.candidates, start=1)],
            },
        )
        logger.info("MTF daily SCAN session=%s run=%s status=%s", d, result.run_id, status)
        return {"status": status, "run_id": row.id, "scanner_run_id": result.run_id}

    async def _run_scanner(self, db, request):
        if self._scanner is not None:
            return await self._scanner(db, request)
        from app.db.redis_client import get_redis
        from app.services.scanner_service import run_scanner
        from app.services.settings_service import get_scanner_settings

        redis = self._redis_getter() if self._redis_getter else get_redis()
        return await run_scanner(request, db, await get_scanner_settings(redis))

    async def run_generate(self, t: dt.date, forced: bool = False) -> dict:
        from app.services.mtf_suggestion_adapter import run_mtf_adapter
        from app.services.scanner_service import get_scanner_results

        row = await self._claim(STAGE_GENERATE, t, forced)
        if row is None:
            return {"status": "ALREADY_DONE"}
        scan_d = previous_trading_day(t)
        async with self._session() as db:
            scan = (await db.execute(
                select(MtfCollectionRun).where(
                    MtfCollectionRun.stage == STAGE_SCAN, MtfCollectionRun.session_date == scan_d,
                    MtfCollectionRun.dry_run == self.dry_run, MtfCollectionRun.status == COMPLETED,
                ).order_by(MtfCollectionRun.id.desc())
            )).scalars().first()
        if scan is None:
            await self._finish(row.id, status=SKIPPED_NO_SCAN,
                               reason=f"no completed {'DRY' if self.dry_run else 'LIVE'} SCAN for {scan_d.isoformat()}")
            return {"status": SKIPPED_NO_SCAN, "run_id": row.id}

        try:
            async with self._session() as db:
                results = await get_scanner_results(db, scan.scanner_run_id)
                ranked = list(enumerate(results.candidates, start=1)) if results else []
                research = await self._research_context(db, t, [c.symbol for _, c in ranked])
                adapter_settings = self.settings.model_copy(update={
                    "enable_mtf_suggestion_adapter": True, "mtf_suggestion_dry_run": self.dry_run,
                })
                adapter = self._adapter or run_mtf_adapter
                out = await adapter(
                    db, ranked, scan.scanner_run_id, settings=adapter_settings, persist_override=not self.dry_run,
                    research_context=research,
                    extra_metadata={"collection_run_id": row.id, "scan_collection_run_id": scan.id,
                                    "scan_session_date": scan_d.isoformat(),
                                    "scan_candle_basis": "COMPLETED_DAILY_CANDLES"},
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("MTF daily GENERATE failed")
            await self._finish(row.id, status=FAILED, scan_collection_run_id=scan.id,
                               scanner_run_id=scan.scanner_run_id, reason=f"{type(exc).__name__}: {str(exc)[:300]}")
            return {"status": FAILED, "run_id": row.id}

        status = COMPLETED if out["eligible"] else NO_VALID_SETUP
        await self._finish(
            row.id, status=status, scan_collection_run_id=scan.id, scanner_run_id=scan.scanner_run_id,
            candidates=out["evaluated"], eligible=out["eligible"], rejected=out["rejected"], persisted=out["persisted"],
            summary={"mode": out["mode"], "results": [_compact(r) for r in out["results"]]},
        )
        logger.info("MTF daily GENERATE session=%s status=%s eligible=%s persisted=%s",
                    t, status, out["eligible"], out["persisted"])
        return {"status": status, "run_id": row.id, "eligible": out["eligible"], "persisted": out["persisted"]}

    async def _research_context(self, db, session_date: dt.date, symbols: list[str]) -> dict:
        """Latest genuine Phase 6 observation per symbol from the generation
        session that was recorded BEFORE now -- labelled with its source and
        time; missing symbols simply have no research context."""
        from app.models.research_market_snapshot import ResearchMarketSnapshot
        from app.models.research_observation import ResearchObservation

        now = self._clock()
        out: dict = {}
        for sym in symbols:
            obs = (await db.execute(
                select(ResearchObservation).where(
                    ResearchObservation.symbol == sym, ResearchObservation.session_date == session_date,
                    ResearchObservation.timestamp_utc <= now,
                ).order_by(ResearchObservation.timestamp_utc.desc())
            )).scalars().first()
            if obs is None:
                continue
            snap = await db.get(ResearchMarketSnapshot, obs.market_snapshot_id) if obs.market_snapshot_id else None
            out[sym] = {
                "source": f"ResearchObservation {obs.id} at {obs.timestamp_utc.isoformat()}",
                "research_confirmation_score": obs.research_confirmation_score, "research_rank": obs.research_rank,
                "research_status": obs.research_status, "sector_participation": obs.sector_participation,
                "divergence": obs.divergence_classification, "research_minus_mtf": obs.research_minus_mtf,
                "stock_return_5d": obs.stock_return_5d, "stock_return_20d": obs.stock_return_20d,
                "stock_vs_sector_20d": obs.stock_vs_sector_20d, "stock_vs_nifty_20d": obs.stock_vs_nifty_20d,
                "live_confirmation_status": obs.live_confirmation_status, "delivery_state": obs.delivery_state,
                "vix_regime": snap.vix_regime if snap else None, "india_vix": snap.india_vix if snap else None,
                "global_risk_sentiment": snap.global_risk_sentiment if snap else None,
                "nifty_regime": snap.nifty_regime if snap else None,
            }
        return out

    async def status(self, db=None) -> dict:
        if db is None:
            async with self._session() as own:
                return await self.status(own)
        rows = (await db.execute(select(MtfCollectionRun).order_by(MtfCollectionRun.id.desc()).limit(20))).scalars().all()
        return {
            "enabled": self.settings.enable_mtf_daily_collection, "state": self.state, "dry_run": self.dry_run,
            "schedule_ist": {"scan": self.settings.mtf_daily_scan_time_ist,
                             "generate": f"{self.settings.mtf_daily_generate_time_ist}-"
                                         f"{self.settings.mtf_daily_generate_deadline_ist}"},
            "last_tick": self.last_tick,
            "recent_runs": [run_dict(r) for r in rows],
        }


def _compact(r: dict) -> dict:
    return {
        "symbol": r["symbol"], "rank": r["rank"], "mtf_score": r["mtf_score"], "eligible": r["eligible"],
        "rejection_reasons": r["rejection_reasons"], "creation_status": r["creation_status"],
        "suggestion_id": r["suggestion_id"], "generation_price_status": r["generation_price"]["status"],
        "level_quality": {k: v["quality"] for k, v in r["levels"].items()},
    }


def run_dict(r: MtfCollectionRun) -> dict:
    return {
        "id": r.id, "stage": r.stage, "session_date": r.session_date.isoformat(), "dry_run": r.dry_run,
        "forced": r.forced, "status": r.status, "reason": r.reason, "scanner_run_id": r.scanner_run_id,
        "scan_collection_run_id": r.scan_collection_run_id, "candidates": r.candidates, "eligible": r.eligible,
        "rejected": r.rejected, "persisted": r.persisted,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }


_collector: MtfDailyCollector | None = None


def get_daily_collector() -> MtfDailyCollector:
    global _collector
    if _collector is None:
        _collector = MtfDailyCollector()
    return _collector
