/**
 * Mirrors backend/app/schemas/stock.py and the CandidateResponse /
 * StockAnalysisResponse shapes in backend/app/schemas/scanner.py. These are
 * the exact JSON shapes returned by GET /api/stocks/{symbol}/analysis and
 * (for CandidateResponse) embedded in the scanner endpoints.
 */
import {
  DataQuality,
  EvidenceItem,
  InstitutionalFootprint,
  PositionSizing,
  ScenarioLevels,
  ScoreComponent,
  SetupDetection,
  SignalQuality,
} from "./api";

export type TrendStructure =
  | "STRONG_UPTREND"
  | "UPTREND"
  | "RANGE_BOUND"
  | "DOWNTREND"
  | "STRONG_DOWNTREND"
  | "INSUFFICIENT_DATA";

export type BreakoutStatus = "BREAKOUT" | "APPROACHING_BREAKOUT" | "NO_BREAKOUT" | "INSUFFICIENT_DATA";

export type PullbackStatus =
  | "PULLBACK_TO_SUPPORT"
  | "DEEP_PULLBACK"
  | "NO_PULLBACK"
  | "NOT_APPLICABLE"
  | "INSUFFICIENT_DATA";

export type FnoPositioningProxy =
  | "LONG_BUILDUP_PROXY"
  | "SHORT_BUILDUP_PROXY"
  | "SHORT_COVERING_PROXY"
  | "LONG_UNWINDING_PROXY"
  | "NEUTRAL"
  | "NOT_AVAILABLE";

export type NewsSentiment = "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "UNKNOWN";
export type RelativeStrengthLabel = "OUTPERFORM" | "UNDERPERFORM" | "NEUTRAL" | "INSUFFICIENT_DATA";
export type SectorStrengthLabel = "STRONG" | "WEAK" | "NEUTRAL" | null;
export type MarketRegime = "RISK_ON" | "RISK_OFF" | "NEUTRAL" | "INSUFFICIENT_DATA" | null;

export interface MarketData {
  price: number;
  change_pct: number | null;
  volume: number | null;
  avg_volume_20d: number | null;
  day_high: number | null;
  day_low: number | null;
  week_52_high: number | null;
  week_52_low: number | null;
  as_of: string;
}

export interface TechnicalData {
  ema_20: number | null;
  ema_50: number | null;
  ema_200: number | null;
  rsi_14: number | null;
  atr_14: number | null;
  adx_14: number | null;
  vwap: number | null;
  recent_high_20d: number | null;
  recent_low_20d: number | null;
  support_level: number | null;
  resistance_level: number | null;
  trend_structure: TrendStructure;
  breakout_status: BreakoutStatus;
  pullback_status: PullbackStatus;
}

export interface VolumeData {
  volume_ratio: number | null;
  relative_volume: number | null;
  high_volume_up_days_20d: number | null;
  high_volume_down_days_20d: number | null;
  breakout_volume: number | null;
  accumulation_score: number | null;
  evidence: EvidenceItem[];
}

export interface FnoData {
  is_available: boolean;
  futures_price_change_pct: number | null;
  futures_oi_change_pct: number | null;
  put_call_oi_ratio: number | null;
  positioning_proxy: FnoPositioningProxy;
  evidence: EvidenceItem[];
}

export interface FundamentalData {
  is_available: boolean;
  revenue_growth_yoy_pct: number | null;
  profit_growth_yoy_pct: number | null;
  eps: number | null;
  net_margin_pct: number | null;
  debt_to_equity: number | null;
  roe_pct: number | null;
  roce_pct: number | null;
  pe_ratio: number | null;
}

export interface NewsCatalystItem {
  headline: string;
  category: string | null;
  sentiment: NewsSentiment;
  source: string;
  source_url: string | null;
  published_at: string;
}

export interface NewsData {
  items: NewsCatalystItem[];
  overall_sentiment: NewsSentiment;
}

export interface RelativeStrengthData {
  label: RelativeStrengthLabel;
  vs_nifty_pct_20d: number | null;
  vs_sector_pct_20d: number | null;
}

export interface SectorData {
  sector_name: string | null;
  sector_strength_label: SectorStrengthLabel;
  market_regime: MarketRegime;
  relative_strength: RelativeStrengthData;
}

export interface StockSummary {
  symbol: string;
  company_name: string;
  sector: string | null;
  is_fno: boolean;
  is_mtf_eligible: boolean;
}

/** The AI research note shape from app/ai/research_engine.py. `sections`
 * always has the 8 required headers as keys, even when AI_PROVIDER=none
 * (in which case every value is an explicit "not configured" string). */
export interface AiResearch {
  sections: Record<string, string>;
  raw_text: string | null;
  flagged_unverified_numbers: string[];
}

/** One ranked MTF candidate -- returned by both scanner endpoints and
 * embedded in the single-stock analysis endpoint. This is the backend's
 * single source of truth for score, evidence, and every risk figure. */
export interface CandidateResponse {
  symbol: string;
  company_name: string;
  sector: string | null;

  score: number;
  score_components: ScoreComponent[];
  signal_quality: SignalQuality;

  price: number;
  entry_zone_low: number;
  entry_zone_high: number;
  invalidation: number;
  scenarios: ScenarioLevels;

  setup: SetupDetection;
  institutional_footprint: InstitutionalFootprint;

  technical: TechnicalData;
  volume: VolumeData;
  fno: FnoData;
  fundamentals: FundamentalData;
  relative_strength: RelativeStrengthData;
  sector_context: SectorData;
  news: NewsData;

  position_sizing: PositionSizing;

  evidence: EvidenceItem[];
  risks: string[];

  data_quality: DataQuality;

  ai_research: AiResearch | null;
}

export interface StockAnalysisResponse {
  symbol: string;
  company_name: string;
  market_data: MarketData;
  candidate: CandidateResponse;
  ai_research: AiResearch | null;
}
