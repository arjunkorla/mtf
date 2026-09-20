Build a production-quality frontend for a focused financial research application called:

**AI MTF Stock Recommendation Engine**

This is NOT a trading terminal and NOT a replacement for FYERS.

The application has one purpose:

**Analyze the NSE stock universe and present the top 3–10 MTF candidates for a 1–4 week holding period, explain why each candidate was selected, show evidence of accumulation/institutional-footprint proxies, identify risks, calculate position sizing, and provide a detailed evidence-based research report.**

The backend will be developed separately using Claude Code in VS Code with Python/FastAPI and FYERS APIs.

==================================================

1. FRONTEND TECHNOLOGY
   ==================================================

Use:

* React
* TypeScript
* Vite
* Tailwind CSS
* React Router
* TanStack Query
* Lucide React icons
* Recharts only where a small supporting visualization is genuinely useful
* Modern component architecture
* Responsive desktop-first design
* Clean financial/research application UX

Do NOT use a heavy UI framework unless necessary.

Keep the code modular and production-ready.

==================================================
2. IMPORTANT PRODUCT PRINCIPLE
==============================

Do NOT build a FYERS clone.

Do NOT build:

* Trading terminal
* Order placement
* Order book
* Market depth screen
* Watchlist
* Portfolio screen
* Large market dashboard
* Complex charting terminal
* Multiple unnecessary navigation sections
* Options trading terminal
* Intraday trading interface

The user already has FYERS for those functions.

This application is an:

**AI-powered MTF stock research and recommendation engine.**

==================================================
3. ONLY TWO MAIN PAGES
======================

Create only:

PAGE 1:
**MTF Scanner**

PAGE 2:
**Detailed Stock Analysis**

Optional small Settings panel/modal:

* Available capital
* Maximum risk per trade
* Maximum number of positions
* MTF preference
* Scan universe

Do not create unnecessary pages.

==================================================
4. PAGE 1 — MTF SCANNER
=======================

Create a clean scanner interface.

Header:

AI MTF STOCK SCANNER

Subtitle:

"Evidence-based 1–4 week MTF opportunities"

Top controls:

Available Capital
₹ [100000]

Risk Per Trade
[2%]

Maximum Positions
[3]

Holding Period
[1–4 weeks]

[ RUN SCAN ]

Display:

Last scan time
Market data timestamp
Data freshness
Number of stocks analyzed

==================================================
5. SCANNER RESULTS
==================

Display ONLY the top 3–10 candidates.

Each stock should appear as a compact research card or table row.

Example:

---

#1

RELIANCE
Reliance Industries Ltd.

MTF SETUP SCORE
84 / 100

Signal Quality
HIGH

Current Price
₹1,420

Entry Zone
₹1,395 – ₹1,425

Invalidation
₹1,350

Scenario 1
₹1,480

Scenario 2
₹1,540

Potential Holding Period
1–4 weeks

Suggested Capital
₹30,000

Estimated Risk
₹1,500

WHY SELECTED

✓ Volume expansion
✓ Positive price-volume structure
✓ Relative strength vs NIFTY
✓ Sector strength
✓ Positive F&O positioning
✓ Technical trend alignment

RISKS

⚠ Resistance nearby
⚠ Upcoming event
⚠ Extended from moving average

[ VIEW DETAILED ANALYSIS ]

---

Do not display fake values.

For initial frontend development use clearly labelled mock data.

==================================================
6. SCORE
========

Show a transparent score.

Example:

MTF SETUP SCORE: 84 / 100

Breakdown:

Technical Structure       18 / 20
Volume / Accumulation     18 / 20
Relative Strength         13 / 15
F&O Positioning           13 / 15
Fundamentals               8 / 10
Catalyst / News            7 / 10
Market / Sector             4 / 5
Data Quality                3 / 5

Total                       84 / 100

The frontend must never imply that the score guarantees future returns.

Use terminology:

"MTF Setup Score"

NOT:

"Profit Score"

NOT:

"Guaranteed Return"

==================================================
7. INSTITUTIONAL FOOTPRINT
==========================

This is a critical part of the application.

Create an evidence section called:

**Institutional Footprint Proxy**

Never display:

"Institutions are definitely buying."

Instead display observable evidence.

Example:

Institutional Footprint Proxy
STRONG

Evidence:

Volume expansion
2.4× 20-day average

Price-volume behaviour
Positive

Relative strength
Strong

Accumulation evidence
Detected

F&O positioning
Long-buildup proxy

Delivery evidence
Available / Not Available

Important disclaimer:

"These are market-behaviour proxies and do not prove institutional buying."

==================================================
8. DETAILED ANALYSIS PAGE
=========================

When the user clicks:

VIEW DETAILED ANALYSIS

Open the detailed stock research page.

Header:

ABC LTD

NSE: ABC

MTF SETUP SCORE
84 / 100

Signal Quality
HIGH

Data Quality
94%

Holding Horizon
1–4 weeks

==================================================
9. "WHY THIS STOCK?"
====================

This should be the most important section.

Title:

**Why This Stock Was Selected**

Show an AI-generated evidence summary.

Example:

"This stock was selected because multiple independent signals currently align. The strongest evidence is the combination of elevated volume, relative strength, improving price structure and supportive F&O positioning."

Then show:

STRONG EVIDENCE

1. Volume
2. Price structure
3. Relative strength
4. F&O positioning
5. Sector strength
6. Catalyst/news
7. Fundamentals

Every statement must be traceable to backend data.

==================================================
10. ACCUMULATION ANALYSIS
=========================

Create:

**Accumulation Evidence**

Show:

Volume vs average
Price-volume relationship
Consolidation behaviour
Breakout behaviour
Delivery data if available
Relative strength
F&O behaviour

Use statuses:

Strong
Moderate
Weak
Neutral
Insufficient Data

Never convert missing data into a positive signal.

==================================================
11. TECHNICAL SETUP
===================

Show only the information required to understand the MTF setup.

Example:

Trend
Bullish / Neutral / Bearish

EMA 20
₹XXX

EMA 50
₹XXX

RSI
XX

ADX
XX

ATR
XX

Recent breakout
Detected / Not detected

Support
₹XXX

Resistance
₹XXX

Do not build a large trading charting interface.

A small supporting visual is acceptable if useful.

==================================================
12. F&O ANALYSIS
================

Show:

Open Interest behaviour
Price/OI relationship
Futures positioning proxy
Put/Call information where available
Options concentration where reliable

Use terminology:

"F&O Positioning"

"Long-buildup proxy"

"Short-buildup proxy"

"OI expansion"

Never claim certainty about trader identity.

==================================================
13. CATALYST / NEWS
===================

Show only relevant recent catalysts.

Examples:

Results
Order wins
Corporate announcements
Capacity expansion
Acquisition
Sector event
Regulatory development

Each item should contain:

Date
Headline
Impact classification

Positive
Neutral
Negative
Unknown

Do not invent news.

==================================================
14. RISK ANALYSIS
=================

Create a prominent section:

**What Could Go Wrong?**

Show actual detected risks.

Examples:

Price already extended
Resistance nearby
Weak market regime
Sector weakness
Upcoming results
Negative news
Low liquidity
High ATR
Conflicting F&O signal

Also show:

**Invalidation Conditions**

Example:

"The setup becomes invalid if price closes below ₹XXX with elevated selling volume."

This must come from backend calculations.

==================================================
15. MTF TRADE SCENARIO
======================

Create:

**MTF Trade Scenario**

Entry Zone
₹XXX – ₹XXX

Preferred Entry
₹XXX

Invalidation
₹XXX

Scenario 1
₹XXX

Scenario 2
₹XXX

Holding Period
1–4 weeks

Risk / Reward
X.X : 1

Do NOT call these guaranteed targets.

Use:

"Scenario"

"Resistance"

"Potential objective"

"Invalidation"

==================================================
16. POSITION SIZING
===================

Create:

**Position Sizing**

Available Capital
₹100,000

Maximum Risk
2%

Maximum Rupee Risk
₹2,000

Entry Price
₹500

Invalidation
₹480

Risk Per Share
₹20

Calculated Quantity
100 shares

Capital Required
₹50,000

MTF Capital Requirement
[backend value]

Important:

Position sizing must be calculated by the backend.

Frontend only displays the result.

==================================================
17. AI RESEARCH SUMMARY
=======================

Create a section:

**AI Research Summary**

Structure:

WHY IT APPEARED

Strongest Evidence

Conflicting Evidence

Key Risks

What Would Confirm the Setup

What Would Invalidate the Setup

Expected Monitoring Period

Do not use language such as:

"Buy immediately"

"This stock will definitely rise"

"Guaranteed target"

"Sure-shot stock"

"100% institutional buying"

Instead use evidence-based language.

==================================================
18. FRONTEND API ARCHITECTURE
=============================

The frontend must NEVER directly connect to FYERS.

Architecture:

Figma Make React Frontend
↓
FastAPI Backend
↓
Scanner Engine
↓
FYERS APIs
↓
Database / Cache

Create API abstraction files:

src/api/client.ts
src/api/scannerApi.ts
src/api/stockApi.ts
src/api/settingsApi.ts

Create types:

src/types/scanner.ts
src/types/stock.ts
src/types/analysis.ts
src/types/risk.ts
src/types/api.ts

Use:

VITE_API_BASE_URL

Example:

VITE_API_BASE_URL=http://localhost:8000/api

Never put:

FYERS_CLIENT_ID
FYERS_SECRET_KEY
FYERS_ACCESS_TOKEN

inside the frontend.

==================================================
19. MOCK DATA
=============

Initially the frontend must work without the backend.

Create:

src/mock/scannerData.ts
src/mock/stockAnalysisData.ts

Use realistic but clearly labelled DEMO DATA.

Create an API mode:

VITE_USE_MOCK_DATA=true

When:

VITE_USE_MOCK_DATA=false

the frontend should call the FastAPI backend.

The UI must not need to change when switching from mock data to real API data.

==================================================
20. API RESPONSE CONTRACT
=========================

Design the frontend around structured backend responses.

Scanner response example:

{
"scan_time": "...",
"market_regime": "...",
"stocks_analyzed": 500,
"results": [
{
"symbol": "ABC",
"company_name": "...",
"score": 84,
"signal_quality": "HIGH",
"current_price": 500,
"entry_zone": {
"low": 490,
"high": 510
},
"invalidation": 470,
"scenarios": [
540,
580
],
"holding_period": "1-4 weeks",
"position_sizing": {
"quantity": 100,
"capital_required": 50000,
"max_risk": 3000
},
"evidence": [],
"risks": [],
"data_quality": 94
}
]
}

Create TypeScript interfaces for these responses.

Do not hard-code backend calculations into React.

==================================================
21. DESIGN SYSTEM
=================

Design should feel like:

Professional
Minimal
Data-driven
Premium financial research platform

Avoid:

Overloaded dashboards
Excessive cards
Neon trading-terminal styling
Too many colors
Unnecessary animations

Use visual hierarchy to emphasize:

Score
Why selected
Institutional footprint proxy
Entry/invalidation
Risk
Position sizing

Use accessible typography and spacing.

==================================================
22. RESPONSIVE DESIGN
=====================

Desktop-first because this is a research tool.

Also support:

Tablet
Mobile

On mobile:

Stack stock information vertically.

Do not create horizontal overflow.

==================================================
23. STATES
==========

Implement:

Loading
Scanning
Success
No candidates
API error
Partial data
Stale data
Insufficient data

For example:

"Insufficient data — score not calculated."

Never display misleading positive information when data is missing.

==================================================
24. SECURITY
============

Frontend must never contain:

FYERS secret
FYERS access token
Database credentials
AI provider secret

All secrets remain on the FastAPI backend.

==================================================
25. FINAL UX FLOW
=================

USER OPENS APP

↓

Enters available capital

↓

Selects risk per trade

↓

Clicks RUN SCAN

↓

Backend analyzes NSE universe

↓

Frontend displays TOP 3–10 candidates

↓

User clicks a stock

↓

Detailed Stock Analysis opens

↓

User sees:

WHY SELECTED
↓
INSTITUTIONAL FOOTPRINT PROXY
↓
TECHNICAL EVIDENCE
↓
F&O EVIDENCE
↓
CATALYSTS
↓
RISKS
↓
ENTRY / INVALIDATION
↓
POSITION SIZING
↓
AI RESEARCH SUMMARY

The application should help the user make an informed trading decision, not automatically place trades.

==================================================
26. IMPLEMENTATION ORDER
========================

Build in this order:

1. Design system
2. Application shell
3. MTF Scanner page
4. Scanner result cards
5. Detailed Stock Analysis page
6. Position sizing components
7. Evidence components
8. Risk components
9. Mock data
10. API abstraction
11. Loading/error/empty states
12. Responsive behavior

Make the application functional with mock data before connecting the backend.

Do not build additional pages unless explicitly requested.
