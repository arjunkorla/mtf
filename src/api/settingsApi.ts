import { ScannerRunRequest, ScannerSettings } from "../types/scanner";
import { client } from "./client";

const RUN_PARAMS_KEY = "mtf_scan_run_params";

const DEFAULT_RUN_PARAMS: ScannerRunRequest = {
  available_capital: 100000,
  risk_percent: 2,
  max_positions: 3,
  holding_period: "1-4 weeks",
};

/** Per-run capital/risk parameters the user sets on the scanner form. These
 * are local UI convenience state only (persisted so the form isn't blank on
 * reload) -- not backend configuration. */
export function loadScanRunParams(): ScannerRunRequest {
  try {
    const stored = localStorage.getItem(RUN_PARAMS_KEY);
    if (stored) return { ...DEFAULT_RUN_PARAMS, ...JSON.parse(stored) };
  } catch {
    /* ignore -- fall back to defaults */
  }
  return DEFAULT_RUN_PARAMS;
}

export function saveScanRunParams(params: ScannerRunRequest): void {
  try {
    localStorage.setItem(RUN_PARAMS_KEY, JSON.stringify(params));
  } catch {
    /* ignore -- non-fatal */
  }
}

/** GET /api/settings -- server-side scanner configuration (candidate
 * filters). Always calls the real backend, even in mock mode, since these
 * settings only affect the (mocked-away) scan itself; a mock default is
 * returned instead when VITE_USE_MOCK_DATA=true so the Advanced Settings
 * panel still renders without a running backend. */
const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

const MOCK_SCANNER_SETTINGS: ScannerSettings = {
  min_price: 20,
  min_avg_daily_turnover: 50000000,
  min_avg_daily_volume: 100000,
  min_history_days: 100,
  max_candidates: 10,
  min_candidates: 3,
  mtf_eligible_only: true,
  fno_only: false,
  exclude_penny_stocks: true,
  default_holding_period: "1-4 weeks",
  default_risk_percent: 2,
  ai_provider: "none",
};

export function getScannerSettings(): Promise<ScannerSettings> {
  if (USE_MOCK) return Promise.resolve(MOCK_SCANNER_SETTINGS);
  return client.get<ScannerSettings>("/settings");
}

export function updateScannerSettings(settings: ScannerSettings): Promise<ScannerSettings> {
  if (USE_MOCK) return Promise.resolve(settings);
  return client.put<ScannerSettings>("/settings", settings);
}
