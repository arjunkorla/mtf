/** Mirrors backend/app/schemas/confirmation.py (RealtimeConfirmationResponse).
 * This is a confirmation layer for the existing MTF score, not a
 * replacement -- see RealtimeConfirmation.tsx for how it's kept visually
 * separate.
 */

export interface EvidenceItem {
  label: string;
  detail: string;
  value: number | string | null;
  is_positive: boolean | null;
}

export interface PriceConfirmationData {
  status: "ABOVE_ENTRY_ZONE" | "INSIDE_ENTRY_ZONE" | "BELOW_ENTRY_ZONE" | "UNAVAILABLE";
  near_invalidation: boolean | null;
  breakout_relation: "ABOVE_BREAKOUT_LEVEL" | "BELOW_BREAKOUT_LEVEL" | "NO_BREAKOUT_LEVEL" | "UNAVAILABLE";
  observed_price: number | null;
  entry_zone_low: number;
  entry_zone_high: number;
  invalidation: number;
}

export interface VolumeConfirmationData {
  status: "EXPANDING" | "NORMAL" | "DECLINING" | "INSUFFICIENT_DATA";
  volume_ratio: number | null;
  baseline: string;
}

export interface VwapConfirmationData {
  status: "ABOVE_VWAP" | "NEAR_VWAP" | "BELOW_VWAP" | "UNAVAILABLE";
  reason_unavailable: string | null;
}

export interface DepthConfirmationData {
  status: "STRONG_BID" | "MODERATE_BID" | "BALANCED" | "MODERATE_ASK" | "STRONG_ASK" | "UNAVAILABLE";
  bid_quantity_total: number | null;
  ask_quantity_total: number | null;
  depth_imbalance: number | null;
  formula: string;
  ladder_totals_consistent: boolean | null;
}

export interface SpreadConditionData {
  status: "HEALTHY" | "WIDE" | "UNAVAILABLE";
  spread: number | null;
  spread_percentage: number | null;
}

export interface FuturesConfirmationData {
  status: "PRICE_UP_OI_UP" | "PRICE_UP_OI_DOWN" | "PRICE_DOWN_OI_UP" | "PRICE_DOWN_OI_DOWN" | "FLAT" | "UNAVAILABLE";
  futures_price_change_pct: number | null;
  futures_oi_change_pct: number | null;
  positioning_proxy: string | null;
}

export interface PersistenceData {
  status: "INSUFFICIENT_OBSERVATIONS" | "STRENGTHENING" | "PERSISTED" | "WEAKENING" | "DISAPPEARED";
  observation_count: number;
  window: number;
  first_observed_status: string | null;
  latest_status: string | null;
}

export type ConfirmationStatus = "STRONGLY_SUPPORTIVE" | "SUPPORTIVE" | "NEUTRAL" | "CONTRADICTORY" | "INSUFFICIENT_DATA";
export type ConfirmationDataQuality = "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT_DATA";

export type MarketStatus = "MARKET_OPEN_LIVE" | "MARKET_CLOSED_LAST_AVAILABLE" | "STALE" | "UNAVAILABLE";

export interface RealtimeConfirmationResponse {
  symbol: string;
  timestamp: string;
  freshness: "LIVE" | "STALE" | "UNAVAILABLE";
  market_status: MarketStatus;
  confirmation_status: ConfirmationStatus;
  confirmation_score: number | null;
  data_quality: ConfirmationDataQuality;

  price_confirmation: PriceConfirmationData;
  volume_confirmation: VolumeConfirmationData;
  vwap_confirmation: VwapConfirmationData;
  depth_confirmation: DepthConfirmationData;
  spread_condition: SpreadConditionData;
  futures_confirmation: FuturesConfirmationData;
  persistence: PersistenceData;

  evidence: EvidenceItem[];
  warnings: string[];
}
