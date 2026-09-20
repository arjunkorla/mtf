/**
 * Generic API plumbing types, plus the small "building block" shapes that
 * are shared by both the scanner-results contract and the stock-analysis
 * contract (they mirror backend/app/schemas/common.py exactly).
 */

export class ApiError extends Error {
  /** HTTP status code, when the backend responded (even with an error). */
  status?: number;
  /**
   * True when the request never reached the backend at all (connection
   * refused, DNS failure, timeout) as opposed to the backend responding
   * with an error status. Callers use this to show
   * "Backend unavailable. Start the FastAPI server and try again."
   * instead of a generic error.
   */
  isNetworkError: boolean;

  constructor(message: string, opts: { status?: number; isNetworkError?: boolean } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status;
    this.isNetworkError = opts.isNetworkError ?? false;
  }
}

export type SignalQuality = "HIGH" | "MEDIUM" | "LOW";

/** Matches InstitutionalFootprintLevel in the backend (also reused for
 * generic evidence-strength display). */
export type SignalStrength = "STRONG" | "MODERATE" | "WEAK" | "NEUTRAL" | "INSUFFICIENT_DATA";

export interface EvidenceItem {
  label: string;
  detail: string;
  value: number | string | null;
  is_positive: boolean | null;
}

export interface ScoreComponent {
  name: string;
  weight: number;
  points_awarded: number | null;
  available: boolean;
  reason_unavailable: string | null;
  evidence: EvidenceItem[];
}

export interface DataQuality {
  data_quality_score: number;
  missing_data: string[];
  stale_data: string[];
  source_timestamps: Record<string, string>;
}

export interface ScenarioLevels {
  entry_zone_low: number;
  entry_zone_high: number;
  preferred_entry: number;
  invalidation: number;
  resistance_scenario_1: number;
  resistance_scenario_1_label: string;
  resistance_scenario_2: number | null;
  resistance_scenario_2_label: string;
}

export interface PositionSizing {
  available_capital: number;
  risk_percent: number;
  entry_price: number;
  invalidation_price: number;
  risk_per_share: number;
  max_rupee_risk: number;
  quantity: number;
  capital_required: number;
  capital_utilization_pct: number;
  reward_to_risk_scenario_1: number | null;
  reward_to_risk_scenario_2: number | null;
  notes: string[];
}

export interface InstitutionalFootprint {
  institutional_footprint_score: number | null;
  institutional_footprint_level: SignalStrength;
  evidence: EvidenceItem[];
}

export interface SetupDetection {
  setup_type: string;
  setup_strength: "HIGH" | "MEDIUM" | "LOW" | null;
  supporting_evidence: EvidenceItem[];
  conflicting_evidence: EvidenceItem[];
  invalidation_condition: string | null;
}

export interface PositionSizeRequest {
  available_capital: number;
  risk_percent: number;
  entry_price: number;
  invalidation_price: number;
  max_position_pct_of_capital?: number;
}

export interface PositionSizeResponse {
  position_sizing: PositionSizing;
}

export interface ComponentHealth {
  name: string;
  status: "ok" | "degraded" | "down" | "unknown";
  detail: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  app_env: string;
  components: ComponentHealth[];
}
