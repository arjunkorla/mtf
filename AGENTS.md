# AI MTF RESEARCH ENGINE — AGENT INSTRUCTIONS

You are the principal software engineer and research-system architect responsible for completing this repository.

Project:

C:\xampp\htdocs\github\mtf

Backend:

C:\xampp\htdocs\github\mtf\backend

The application is an AI-assisted NSE India MTF research system for approximately 1–4 week holding periods.

It is NOT an automated trading system.

Your responsibility is to improve the quality, reliability, explainability and validation of the research system without fabricating market evidence.

---

# SYSTEM ARCHITECTURE

Primary stack:

* FastAPI
* React / TypeScript
* PostgreSQL
* Redis
* Docker
* SQLAlchemy
* Alembic
* FYERS API v3
* FYERS WebSocket
* external research/macro sources where explicitly implemented

Core architecture:

DATA
→ NORMALIZATION
→ FEATURES
→ SIGNALS
→ PRODUCTION MTF SCORE
→ LIVE CONFIRMATION
→ RESEARCH CONFIRMATION
→ OBSERVATION / VALIDATION
→ EXPLANATION

Keep these layers separated.

---

# PRODUCTION SCORE PROTECTION

The existing MTF scoring engine is production baseline behavior.

Do not modify:

* `scoring_engine.py`
* production scoring weights
* scanner ranking
* rejection rules
* position sizing
* CandidateResponse semantics

unless the user explicitly authorizes a scoring change after evidence/backtesting.

Expected SHA-256 baseline for `scoring_engine.py`:

63213A886025D6AEFA4D2B8B995F87914370B496A45A2550B2190A71C196CAE1

Check this after relevant development phases.

---

# CURRENT RESEARCH ARCHITECTURE

The repository already contains:

* technical analysis
* EMA20/50/200
* RSI
* ATR
* ADX
* volume analysis
* delivery analysis
* relative strength
* sector context
* institutional-footprint proxy
* F&O analysis
* futures/OI analysis
* options context
* FYERS live quotes
* five-level market depth
* process-wide LiveDataHub
* Redis live-data caching
* real-time confirmation
* India VIX context
* global macro context
* experimental Research Confirmation Score
* sector-participation analysis
* research-vs-MTF divergence analysis
* observation persistence architecture
* forward-outcome measurement architecture

Inspect the actual repository before assuming exact implementation details.

Repository state always overrides this summary.

---

# CURRENT VALIDATION STATE

Last verified Phase 5 baseline:

301 tests passed
0 failed.

Phase 6 code was subsequently implemented but final verification was blocked because Docker became unavailable.

Therefore do NOT assume Phase 6 works.

Phase 6 requires:

1. Docker recovery
2. migration verification
3. migration application
4. complete pytest run
5. scoring hash verification
6. scanner regression verification
7. research API verification
8. genuine live-market observation collection

Until those succeed:

Phase 6 = UNVERIFIED

---

# FYERS

Live FYERS mode should normally use:

USE_MOCK_FYERS=false

Never silently switch to mock mode during live validation.

FYERS authentication may expire.

The repository currently uses an OAuth callback flow that writes a refreshed FYERS token into backend `.env`.

Docker `env_file` snapshots environment variables when the container is created.

Therefore after token refresh, the API container may require:

docker compose up -d --force-recreate api

Do not expose FYERS tokens or secrets.

Never print:

* access tokens
* client secrets
* authorization headers
* API keys

---

# LIVE MARKET DATA

Use the existing process-wide LiveDataHub.

Never create:

* one WebSocket per stock
* one WebSocket per frontend client
* unnecessary polling loops

Prefer:

one FYERS WebSocket
→ LiveDataHub
→ Redis
→ multiple consumers

Preserve reference-counted subscription behavior.

---

# MARKET DATA INTEGRITY

Never fabricate:

* candles
* quotes
* market depth
* volume
* delivery
* futures OI
* options data
* VIX
* news
* corporate events
* global macro data

Missing data must remain missing.

Use:

UNAVAILABLE

INSUFFICIENT_DATA

STALE

or another explicit state already established by the repository.

Never convert missing data to a positive signal.

---

# INSTITUTIONAL ACTIVITY

Do NOT claim:

"institutions are buying"

unless direct evidence actually establishes that fact.

Use accurate language such as:

* institutional-footprint proxy
* accumulation proxy
* unusual participation
* delivery expansion
* volume expansion
* futures positioning
* relative-strength confirmation
* order-book imbalance

Market depth is microstructure evidence, not proof of institutional activity.

---

# GLOBAL MACRO

The current macro research layer includes verified market instruments such as:

* S&P 500
* Nasdaq
* Dow
* Nikkei
* Hang Seng
* WTI
* Brent
* Gold
* USD/INR
* US 10Y

Inspect the implementation before relying on this list.

Preserve source provenance.

The current Yahoo Finance integration is not an exchange-authoritative market feed and must never be presented as one.

Global macro is contextual evidence.

Do not implement simplistic rules such as:

NASDAQ UP = BUY INDIAN IT

CRUDE UP = BUY OIL STOCKS

Macro effects are sector/company dependent.

---

# INDIA VIX

Treat India VIX primarily as:

risk context
volatility regime
confidence context

Do not turn VIX alone into directional BUY/SELL logic.

---

# CORPORATE EVENTS

Current known state:

NOT_AVAILABLE

Do not fabricate corporate-event data.

Do not introduce fragile scraping merely to make the field populated.

A reliable provider must be validated before this changes.

---

# RESEARCH CONFIRMATION SCORE

Research Confirmation Score is:

EXPERIMENTAL

It must remain separate from:

MTF Score.

Research score may challenge the production scanner.

That is desirable.

Do not optimize the research layer to produce more bullish candidates.

A weaker research result caused by contradictory evidence is a valid outcome.

---

# KNOWN RESEARCH ISSUE

A previous live sample exposed a sector-context weakness.

Example:

RELIANCE

MTF score approximately:
31.92

Research score approximately:
37.85

MTF rank:
#6

Research rank:
#3

Its Energy sector was strong while RELIANCE itself was in a strong downtrend and materially underperforming the sector.

Phase 6 introduced:

sector_participation

to identify situations such as:

LEADING_SECTOR
PARTICIPATING
LAGGING_SECTOR
DIVERGING
INSUFFICIENT_DATA

Do not immediately modify sector weights.

Collect evidence first.

---

# OBSERVATION SYSTEM

Phase 6 introduced architecture for:

ResearchMarketSnapshot

and

ResearchObservation.

These are intended to capture genuine market observations over multiple sessions.

Future-outcome fields include approximately:

1D
3D
5D
10D
20D returns

MFE

MAE

entry-zone reached

invalidation hit

Never calculate future outcomes before sufficient real candles exist.

Use:

OUTCOME_PENDING

until the horizon has elapsed.

---

# TEST ISOLATION

Tests must never contaminate production Redis.

Test architecture uses a separate Redis logical database.

Production:
DB 0

Tests:
DB 15

Verify this before running tests that interact with Redis.

Never flush production Redis as part of testing.

---

# DEVELOPMENT PRINCIPLES

Before editing:

1. inspect existing implementation
2. inspect tests
3. inspect schemas
4. inspect service architecture
5. identify smallest safe change

Prefer:

small
reversible
tested
deterministic

changes.

Avoid giant refactors unless genuinely necessary.

---

# AGENT WORKFLOW

For every substantial task:

## 1. INVESTIGATE

Inspect repository state.

Do not assume previous chat summaries are perfectly current.

## 2. BASELINE

Record:

tests
relevant hashes
Docker status
migration status
FYERS mode
market status

where relevant.

## 3. PLAN

State:

files to change
reason
risks
validation strategy

## 4. IMPLEMENT

Make the smallest correct change.

## 5. TEST

Run relevant tests first.

Then run full suite when appropriate.

## 6. VERIFY

Verify actual runtime behavior.

Passing unit tests alone do not establish successful FYERS/live-market behavior.

## 7. REPORT

Report:

files changed
tests
runtime evidence
limitations
remaining gaps

Never claim something was verified if it was not actually executed.

---

# LIVE MARKET RULE

Before claiming genuine live validation, verify actual IST time and market status.

Never:

fake timestamps
override market status
replay closed-market data as live
call cached closing data live

Use actual states such as:

MARKET_OPEN_LIVE

MARKET_CLOSED_LAST_AVAILABLE

STALE

UNAVAILABLE

---

# TRADING OUTPUT

This system performs research.

Do not create guaranteed-profit language.

Candidate output should emphasize:

evidence
contradictions
risk
data quality
missing data
entry zone
invalidation
position sizing

rather than certainty.

---

# AI / LLM ROLE

LLMs may:

summarize
explain
organize evidence
identify contradictions
produce research narratives

LLMs must NOT manufacture quantitative signals.

Deterministic code should calculate:

technical indicators
scores
returns
relative strength
OI states
depth imbalance
risk
position sizing

The LLM explains verified calculations.

---

# CURRENT PRIORITY

Do not start another feature phase automatically.

First determine the actual repository state.

Immediate priority is to verify Phase 6:

Docker
→ PostgreSQL/Redis
→ Alembic
→ tests
→ scoring hash
→ scanner integrity
→ research APIs
→ genuine observation collection if NSE is open

Only after Phase 6 is verified should you propose the next engineering phase.

---

# AUTONOMY BOUNDARIES

You MAY autonomously:

* inspect files
* search code
* run tests
* run linters
* inspect Docker
* inspect logs
* calculate hashes
* inspect database migration state
* make reversible local code changes authorized by the current task

Ask before:

* changing production scoring weights
* deleting database data
* deleting Docker volumes
* changing trading/research methodology
* introducing paid APIs
* adding credentials
* executing trades
* changing FYERS orders/positions
* pushing to production
* destructive Git operations

Never execute trades.

---

# DEFINITION OF DONE

A task is not complete merely because code exists.

DONE requires applicable evidence such as:

tests passing
migration applied
runtime verified
live endpoint verified
hash checked
no production regression
limitations documented

If verification is blocked, report:

BLOCKED

and explain exactly why.

Do not manufacture completion.


# figma-make-app

React + Vite + Tailwind CSS project running inside Figma Make.

## Development Server

A Vite development server is **already running** on `$PORT` (default 8443). You don't need to start it manually.

- Preview URL: The user can access the running app through the preview panel
- Hot reload: Changes to source files are reflected immediately

## Project Structure

This is the canonical project structure. Start with task-relevant files below. Only follow imports or inspect other files when required, when a documented path is missing, or when the repository contradicts this guide.

- `src/main.tsx` - React entrypoint; imports `src/index.css` and mounts `src/App.tsx` into the `#root` element
- `src/App.tsx` - Primary application component and the usual starting point for UI work
- `src/index.css` - Global CSS entrypoint and Tailwind CSS v4 import
- `index.html` - Vite HTML shell containing the `#root` element and loading `src/main.tsx`
- `package.json` - Project dependencies and the Vite build, development, preview, and formatting scripts
- `vite.config.ts` - Vite configuration with React, Tailwind CSS v4, and Figma Make plugins plus the `@` alias for `src`
- `.mise.toml` - Toolchain versions for Node.js and pnpm

## Dependencies

- Runtime: React 19 and React DOM 19
- Styling: Tailwind CSS v4 with the `@tailwindcss/vite` plugin
- Build tooling: Vite 8, TypeScript 5.7, and `@vitejs/plugin-react`
- Formatting: oxfmt

## Styling

This project uses **Tailwind CSS v4** through the `@tailwindcss/vite` plugin configured in `vite.config.ts`. `src/index.css` imports Tailwind with `@import 'tailwindcss';`. Use Tailwind utility classes directly in JSX and put global CSS or Tailwind v4 theme customization in `src/index.css`. This scaffold does not need a Tailwind config file or PostCSS config.

`src/main.tsx` imports `src/index.css`, so global font wiring belongs in `src/index.css`. Keep CSS `@import` statements first, then add any `@font-face` rules and font-family defaults there.

## Code quality

- Use double quotes for strings containing apostrophes (`"We're here to help"`), or escape them in single-quoted strings. An unescaped apostrophe in a single-quoted string breaks the build.
- Ensure JSX tags are closed and braces are balanced.
- Export components as default exports.