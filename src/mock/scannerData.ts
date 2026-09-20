/**
 * Mock data used only when VITE_USE_MOCK_DATA=true. Shaped exactly like the
 * real backend response (ScannerRunResponse / CandidateResponse) so the
 * mock path exercises the same rendering code as the live API -- no
 * separate "mock schema" to keep in sync.
 */
import { ScannerRunResponse } from "../types/scanner";
import { CandidateResponse } from "../types/stock";

export function candidate(overrides: Partial<CandidateResponse> & Pick<CandidateResponse, "symbol" | "company_name">): CandidateResponse {
  const base: CandidateResponse = {
    symbol: overrides.symbol,
    company_name: overrides.company_name,
    sector: "Energy",
    score: 62.9,
    score_components: [
      { name: "technical_structure", weight: 20, points_awarded: 17.6, available: true, reason_unavailable: null, evidence: [] },
      { name: "volume_accumulation", weight: 20, points_awarded: 10.2, available: true, reason_unavailable: null, evidence: [] },
      { name: "relative_strength", weight: 15, points_awarded: 7.5, available: true, reason_unavailable: null, evidence: [] },
      { name: "fno_positioning", weight: 15, points_awarded: 7.5, available: true, reason_unavailable: null, evidence: [] },
      { name: "fundamentals", weight: 10, points_awarded: null, available: false, reason_unavailable: "No validated fundamentals on file for this stock", evidence: [] },
      { name: "catalyst_news", weight: 10, points_awarded: null, available: false, reason_unavailable: "No recent news/catalyst data available", evidence: [] },
      { name: "market_sector", weight: 5, points_awarded: 3.75, available: true, reason_unavailable: null, evidence: [] },
      { name: "data_quality", weight: 5, points_awarded: 3.75, available: true, reason_unavailable: null, evidence: [] },
    ],
    signal_quality: "MEDIUM",
    price: 3705.85,
    entry_zone_low: 3366.49,
    entry_zone_high: 3705.85,
    invalidation: 3330.73,
    scenarios: {
      entry_zone_low: 3366.49,
      entry_zone_high: 3705.85,
      preferred_entry: 3705.85,
      invalidation: 3330.73,
      resistance_scenario_1: 3778.75,
      resistance_scenario_1_label: "Potential objective (near-term resistance)",
      resistance_scenario_2: 3921.77,
      resistance_scenario_2_label: "Potential objective (extended scenario)",
    },
    setup: {
      setup_type: "BREAKOUT_RETEST",
      setup_strength: "MEDIUM",
      supporting_evidence: [
        { label: "Approaching resistance", detail: "Price is within 3% of the 20D high, a potential breakout/retest zone", value: null, is_positive: true },
      ],
      conflicting_evidence: [
        { label: "Overbought RSI", detail: "RSI14 at 80.1, elevated extension risk", value: 80.1, is_positive: false },
      ],
      invalidation_condition: "Daily close below 3348.61 (support/EMA structure)",
    },
    institutional_footprint: {
      institutional_footprint_score: 50.9,
      institutional_footprint_level: "NEUTRAL",
      evidence: [
        { label: "Volume expansion proxy", detail: "Volume running at 1.08x the 20-day average", value: 1.08, is_positive: false },
        { label: "Accumulation behaviour proxy", detail: "Composite accumulation score 51.2/100", value: 51.2, is_positive: false },
        { label: "Relative strength proxy", detail: "Stock is labeled NEUTRAL vs NIFTY over the recent window", value: 0, is_positive: false },
      ],
    },
    technical: {
      ema_20: 3616.2, ema_50: 3455.4, ema_200: 3182.1, rsi_14: 80.1, atr_14: 71.5, adx_14: 69.0, vwap: 3649.7,
      recent_high_20d: 3778.75, recent_low_20d: 3348.61, support_level: 3348.61, resistance_level: 3778.75,
      trend_structure: "STRONG_UPTREND", breakout_status: "APPROACHING_BREAKOUT", pullback_status: "NO_PULLBACK",
    },
    volume: {
      volume_ratio: 1.08, relative_volume: 1.08, high_volume_up_days_20d: 0, high_volume_down_days_20d: 0,
      breakout_volume: null, accumulation_score: 51.2,
      evidence: [
        { label: "Volume vs 20D average", detail: "Latest volume is 1.08x the 20-day average", value: 1.08, is_positive: false },
      ],
    },
    fno: {
      is_available: true, futures_price_change_pct: 0, futures_oi_change_pct: 3.2, put_call_oi_ratio: null,
      positioning_proxy: "NEUTRAL",
      evidence: [{ label: "Futures OI change", detail: "Open interest changed 3.20% vs prior session", value: 3.2, is_positive: false }],
    },
    fundamentals: { is_available: false, revenue_growth_yoy_pct: null, profit_growth_yoy_pct: null, eps: null, net_margin_pct: null, debt_to_equity: null, roe_pct: null, roce_pct: null, pe_ratio: null },
    relative_strength: { label: "NEUTRAL", vs_nifty_pct_20d: 0, vs_sector_pct_20d: null },
    sector_context: {
      sector_name: "Energy", sector_strength_label: null, market_regime: "RISK_ON",
      relative_strength: { label: "NEUTRAL", vs_nifty_pct_20d: 0, vs_sector_pct_20d: null },
    },
    news: { items: [], overall_sentiment: "UNKNOWN" },
    position_sizing: {
      available_capital: 100000, risk_percent: 2, entry_price: 3705.85, invalidation_price: 3330.73,
      risk_per_share: 375.12, max_rupee_risk: 2000, quantity: 5, capital_required: 18529.25,
      capital_utilization_pct: 18.53, reward_to_risk_scenario_1: 0.19, reward_to_risk_scenario_2: 0.58, notes: [],
    },
    evidence: [
      { label: "Volume expansion proxy", detail: "Volume running at 1.08x the 20-day average", value: 1.08, is_positive: false },
      { label: "Accumulation behaviour proxy", detail: "Composite accumulation score 51.2/100", value: 51.2, is_positive: false },
    ],
    risks: [
      "RSI is in overbought territory -- pullback risk is elevated.",
      "Fundamental data is unavailable for this stock.",
      "Missing data sources: fundamentals, news, sector_metrics.",
    ],
    data_quality: {
      data_quality_score: 75,
      missing_data: ["fundamentals", "news", "sector_metrics"],
      stale_data: [],
      source_timestamps: {},
    },
    ai_research: null,
  };
  return { ...base, ...overrides };
}

export const MOCK_SCANNER_RESPONSE: ScannerRunResponse = {
  run_id: 1,
  status: "completed",
  generated_at: new Date().toISOString(),
  holding_period: "1-4 weeks",
  stocks_analyzed: 20,
  stocks_rejected: 15,
  stocks_selected: 5,
  rejection_summary: { insufficient_liquidity: 8, penny_stock_price_below_20: 4, not_mtf_eligible: 3 },
  candidates: [
    candidate({ symbol: "NSE:RELIANCE-EQ", company_name: "Reliance Industries Ltd", score: 62.9 }),
    candidate({
      symbol: "NSE:TCS-EQ", company_name: "Tata Consultancy Services Ltd", sector: "IT", score: 58.4,
      signal_quality: "MEDIUM", price: 4120.0,
      institutional_footprint: { institutional_footprint_score: 44.2, institutional_footprint_level: "WEAK", evidence: [] },
    }),
    candidate({
      symbol: "NSE:HDFCBANK-EQ", company_name: "HDFC Bank Ltd", sector: "Financials", score: 55.1,
      signal_quality: "LOW", price: 1682.0,
      institutional_footprint: { institutional_footprint_score: null, institutional_footprint_level: "INSUFFICIENT_DATA", evidence: [] },
    }),
  ],
};
