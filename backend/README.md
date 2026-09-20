# AI MTF Stock Recommendation Engine -- Backend

NSE MTF (Margin Trading Facility) research backend. **Not a trading terminal** --
no order placement. Identifies 3-10 evidence-backed 1-4 week MTF candidates
from measurable market data and explains why, with every score component,
risk, and data-quality caveat exposed to the frontend.

Consumed by a separate Figma Make React frontend (`../src`) via
`VITE_API_BASE_URL` (e.g. `http://localhost:8000/api`).

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # defaults to USE_MOCK_FYERS=true, no real credentials needed
.\.venv\Scripts\alembic upgrade head   # requires DATABASE_URL to point at a reachable Postgres
.\.venv\Scripts\uvicorn app.main:app --reload
```

Or via Docker Compose (Postgres + Redis + API, with `--reload` for local dev):

```powershell
docker compose up -d --build
docker compose exec api alembic upgrade head   # once, against the containerized Postgres
```

Open http://localhost:8000/api/health, http://localhost:8000/docs.

Note: the `api` service resolves `db`/`redis` by their Compose service names
(overridden in `environment:`, not `.env`'s `localhost` URLs, which are for
running `uvicorn` natively on the host instead). If something else on your
machine is also bound to host port 5432 or 8000 (common with Docker Desktop's
own proxy, or another local Postgres), `docker compose ps` will still show
the container healthy -- the collision only affects host-side tools
connecting to `localhost`, not the containers talking to each other.

To grow the scan universe beyond the 20-symbol dev seed list, run
`docker compose exec api python -m scripts.sync_universe` (see status notes
below) -- this is a separate, explicit step, not automatic.

## Tests

Runs fully offline -- mock FYERS responses, in-memory SQLite, no Redis required:

```powershell
.\.venv\Scripts\pytest tests -q
```

## Layout

- `app/integrations/fyers/` -- FYERS API v3 adapter (REST + auth + live WebSocket); mocked when `USE_MOCK_FYERS=true`
- `app/integrations/news/` -- RSS feed client for the news/catalyst engine
- `app/data/` -- stock universe, validation, provider-agnostic normalization, news matching, sector-index map
- `app/engines/` -- technical, volume, institutional footprint, F&O, relative strength,
  fundamentals, news, market/sector, scoring, setup detection, risk, scenarios, data quality, backtest
- `app/ai/` -- AI research engine (narrates already-computed data; never calculates scores)
- `app/services/` -- orchestration (scanner run, single-stock analysis, caching, settings,
  universe sync, news sync, backtest, live quotes)
- `scripts/sync_universe.py`, `scripts/sync_news.py`, `scripts/run_backtest.py`,
  `scripts/run_walk_forward.py` -- manual/cron entrypoints
- `app/api/routes/` -- the 8 endpoints in the frontend contract, plus the additive `live.py` WebSocket
- `alembic/` -- schema migrations (`stocks`, `price_history`, `technical_metrics`,
  `volume_metrics`, `fno_metrics`, `fundamentals`, `news`, `sector_metrics`, `signals`,
  `scanner_runs`, `scanner_results`)
- `tests/` -- unit tests per engine + integration tests hitting the FastAPI app

## Status vs. the 6-phase plan

Phase 1 (FastAPI, config, FYERS adapter, DB, technical/volume engines, basic
scanner) is functional end-to-end against mock FYERS data -- verified by
`POST /api/scanner/run` returning ranked, fully-scored candidates.

Phases 2-6 are scaffolded with real, working logic wherever the spec gives a
concrete formula (institutional footprint proxy, F&O proxy classification,
risk/position sizing, scoring, AI research prompt).

Deepened since the initial scaffold (2026-09-19), each verified live against
real endpoints/data, not just unit tests:

- **Sector-index relative strength** (section 10/14) -- `app/data/sector_index_map.py`
  maps 7 of the seed universe's sectors to real, confirmed FYERS NSE sectoral
  index symbols (e.g. `NSE:NIFTYIT-INDEX`); `sector_context.sector_strength_label`
  and `relative_strength.vs_sector_pct_20d` are computed from real fetched
  history instead of always being null. Sectors with no confirmed standalone
  NSE index (Telecom, Cement, Diversified, Industrials, Consumer Durables)
  are deliberately left unmapped -- still an honest null, never a guess.
- **NSE symbol-master importer** (section 5) -- `app/services/universe_sync_service.py`
  + `scripts/sync_universe.py` pull the real public FYERS `NSE_CM.csv`
  (confirmed URL, undocumented column layout so every row is defensively
  validated) and upsert into `stocks`. Verified against the live file:
  10,026 rows seen, 2,668 real EQ-series symbols parsed correctly (bonds/
  SGBs/T-bills/mutual-fund-units/trade-to-trade series correctly excluded),
  known large-caps cross-checked by name/ISIN/MTF-eligibility. Deliberately
  NOT wired into the scanner's default hot path -- see the module docstring
  for why (predictable perf/rate-limit exposure). `sector` and `is_fno`
  aren't in this feed, so synced stocks get `sector=None` / `is_fno=False`
  until a future sector-classification and NSE_FO.csv cross-reference pass.
- **Redis caching** (section 23) is now actually called: quotes (15s),
  single-stock analysis (300s), and scanner results (300s) all check/populate
  Redis, degrading to a live fetch (never an error) if Redis is unreachable.
- **Backtesting** (section 24, Phase 6) -- `app/engines/backtest_engine.py`
  (pure, IO-free signal computation + forward-outcome evaluation) and
  `app/services/backtest_service.py` (walks real history day-by-day,
  persists each day's signal to the existing `signals` table, aggregates
  hit-rate/avg-return per setup type) are implemented and verified live via
  `scripts/run_backtest.py`. Look-ahead bias is avoided structurally: every
  calculation is fed a candle slice truncated to the simulated date
  (including the NIFTY/sector benchmarks), and fundamentals/news/F&O are
  excluded entirely rather than substituted with "current" values, since
  this system has no point-in-time history for them. Deliberately a script,
  not a REST endpoint or UI, per section 24.
- **News/catalyst feed** (section 13) -- NSE's own corporate-announcements
  API was tested live and returns HTTP 403 to any non-browser client (too
  fragile/anti-bot-protected to build on). The Economic Times markets RSS
  feed (`app/integrations/news/rss_feed_client.py`) was confirmed live and
  current instead. `app/data/news_matcher.py` matches fetched articles
  against a stock by ticker or full distinctive name phrase (NOT just the
  first word -- an early version cross-matched "Tata Motors" against a TCS
  headline because both start with "Tata"; fixed and regression-tested) and
  classifies category/sentiment with auditable keyword rules.
  `app/services/news_service.py` upserts genuine matches into the `news`
  table (deduped by article URL); wired inline into
  `stock_service.load_stock_context` so both the scanner and
  `/stocks/{symbol}/analysis` pick up fresh news automatically, with
  `scripts/sync_news.py` for bulk pre-warming. A feed outage never breaks
  candidate scoring -- it falls back to whatever's already stored.
- **Live quotes via WebSocket** (section 30, Phase 5) --
  `app/integrations/fyers/websocket.py` wraps the *official* `fyers-apiv3`
  SDK's `FyersDataSocket` for the live path rather than hand-rolling the
  wire protocol: FYERS' own support KB confirms the WebSocket message
  structure "is not provided" publicly, and a wrong guess at binary framing
  would silently produce plausible-looking wrong prices instead of an
  obvious error -- a strictly worse failure mode than a REST guess. The SDK
  import is lazy (only touched in live mode) since its dependency chain
  needs an old, exact-pinned `aiohttp` that fails to build without a C
  compiler on some hosts -- confirmed clean in this project's own Docker
  image (`python:3.12-slim`), where the backend actually runs. A background
  thread bridges ticks into asyncio (`app/services/live_quote_service.py`),
  both into the Redis quote cache and out to a new
  `WS /api/ws/quotes?symbols=...` endpoint, verified with a real network
  WebSocket client round-trip against the running container. Not part of
  the original 8-endpoint contract and the frontend isn't wired to it yet.
  The live (non-mock) tick-handling path itself is implemented to the
  documented sample code but unverified against a real FYERS account -- no
  live credentials were available to test it, the same honesty bar as every
  other "no live credentials" gap in this project.
- **Walk-forward validation** (section 24/30, Phase 6) --
  `app/services/walk_forward_service.py` splits a date range into
  sequential (or overlapping, via `--step-days`) windows and runs
  `backtest_service.run_backtest` independently on each one, reporting
  per-window hit-rate/avg-return side by side plus a combined figure --
  since this system's scoring weights are fixed rather than fitted, this is
  walk-forward *testing* (does the fixed rule set hold up out-of-sample
  across periods), not walk-forward *optimization*. Reports raw per-window
  numbers rather than a synthesized verdict, consistent with the rest of
  this project's evidence-over-verdict approach. `scripts/run_walk_forward.py`
  is the entrypoint. Building this surfaced and fixed a real mock-data gap:
  `mock_history_response` always anchored its generated series to "today"
  regardless of the requested date range, so backtest/walk-forward windows
  further in the past silently got zero candles in mock mode -- fixed to
  honor the requested `range_to`, verified live (a 4-window run that
  previously returned 0 signals for 3 of 4 windows now returns real,
  evaluated signals for all 4).

Still open, deliberately not attempted without the same live-verification
bar as the above (no confirmed public API found with enough confidence to
ship, rather than guessing at one):

- No delivery-percentage data source (institutional footprint engine excludes
  that proxy rather than faking it).

None of these gaps produce fabricated data -- every one surfaces as
`is_available: false`, an empty list, or an `INSUFFICIENT_DATA` label in the
API response.
