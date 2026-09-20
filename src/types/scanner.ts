/**
 * Mirrors backend/app/schemas/scanner.py (ScannerRunRequest/Response) and
 * backend/app/schemas/settings.py (ScannerSettings).
 */
import { CandidateResponse } from "./stock";

/** POST /api/scanner/run request body. Also reused as the shape persisted
 * to localStorage for the scanner form (same fields, same names). */
export interface ScannerRunRequest {
  available_capital: number;
  risk_percent: number;
  max_positions: number;
  holding_period: string;
}

export interface ScannerRunResponse {
  run_id: number;
  status: "running" | "completed" | "failed";
  generated_at: string;
  holding_period: string;
  stocks_analyzed: number;
  stocks_rejected: number;
  stocks_selected: number;
  rejection_summary: Record<string, number>;
  candidates: CandidateResponse[];
}

export interface ScannerResultsResponse {
  run_id: number;
  status: "running" | "completed" | "failed";
  generated_at: string;
  candidates: CandidateResponse[];
}

/** GET/PUT /api/settings -- server-side scanner configuration (section 16
 * of the backend spec). Distinct from ScannerRunRequest, which is the
 * per-run capital/risk input the user provides on the scanner form. */
export interface ScannerSettings {
  min_price: number;
  min_avg_daily_turnover: number;
  min_avg_daily_volume: number;
  min_history_days: number;
  max_candidates: number;
  min_candidates: number;
  mtf_eligible_only: boolean;
  fno_only: boolean;
  exclude_penny_stocks: boolean;
  default_holding_period: string;
  default_risk_percent: number;
  ai_provider: string;
}
