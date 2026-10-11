import { useState, useCallback, useEffect, useRef } from "react";
import {
  ScanLine,
  Settings2,
  Clock,
  Database,
  TrendingUp,
  AlertCircle,
  Loader2,
  ChevronDown,
  XCircle,
} from "lucide-react";
import { ScannerRunRequest, ScannerRunResponse, ScannerSettings } from "../types/scanner";
import { ApiError } from "../types/api";
import { runScan } from "../api/scannerApi";
import { loadScanRunParams, saveScanRunParams, getScannerSettings, updateScannerSettings } from "../api/settingsApi";
import { checkHealth, BACKEND_UNAVAILABLE_MESSAGE } from "../api/client";
import StockCard from "../components/scanner/StockCard";
import FyersStatusBadge from "../components/fyers/FyersStatusBadge";
import FyersAuthPrompt from "../components/fyers/FyersAuthPrompt";
import { useFyersStatus } from "../hooks/useFyersStatus";
import { isFyersAuthRequired } from "../api/fyersAuthState";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

type BackendStatus = "checking" | "ok" | "degraded" | "down";

function ConnectionIndicator({ status }: { status: BackendStatus }) {
  if (USE_MOCK) {
    return (
      <>
        <span className="text-[10px] font-data text-[#475569] hidden sm:block">MOCK DATA</span>
        <span className="w-1.5 h-1.5 rounded-full bg-[#CF8B2E] animate-pulse" />
      </>
    );
  }
  const map: Record<BackendStatus, { label: string; color: string }> = {
    checking: { label: "CONNECTING", color: "#F59E0B" },
    ok: { label: "LIVE", color: "#22C9B4" },
    degraded: { label: "DEGRADED", color: "#F59E0B" },
    down: { label: "BACKEND DOWN", color: "#F05252" },
  };
  const s = map[status];
  return (
    <>
      <span className="text-[10px] font-data text-[#475569] hidden sm:block">{s.label}</span>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
    </>
  );
}

export default function ScannerPage() {
  const [runParams, setRunParams] = useState<ScannerRunRequest>(loadScanRunParams);
  const [scanResult, setScanResult] = useState<ScannerRunResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");
  const fyers = useFyersStatus(!USE_MOCK);
  const recheckFyers = fyers.recheck;
  const [fyersAuthError, setFyersAuthError] = useState(false);

  const [settings, setSettings] = useState<ScannerSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const inFlight = useRef(false);

  useEffect(() => {
    if (USE_MOCK) return;
    checkHealth()
      .then((h) => setBackendStatus(h.status === "ok" ? "ok" : "degraded"))
      .catch(() => setBackendStatus("down"));
  }, []);

  useEffect(() => {
    setSettingsLoading(true);
    getScannerSettings()
      .then(setSettings)
      .catch((e) => setSettingsError(e instanceof Error ? e.message : "Failed to load settings"))
      .finally(() => setSettingsLoading(false));
  }, []);

  const handleScan = useCallback(async () => {
    if (inFlight.current) return; // prevent duplicate requests
    inFlight.current = true;
    setLoading(true);
    setError(null);
    setFyersAuthError(false);
    try {
      saveScanRunParams(runParams);
      const result = await runScan(runParams);
      setScanResult(result);
      setBackendStatus("ok");
    } catch (e) {
      if (isFyersAuthRequired(e)) {
        setFyersAuthError(true);
        setError(e instanceof Error ? e.message : "FYERS session expired.");
        recheckFyers(false);
      } else if (e instanceof ApiError && e.isNetworkError) {
        setBackendStatus("down");
        setError(e.message);
      } else {
        setError(e instanceof Error ? e.message : "Scan failed. Please try again.");
      }
    } finally {
      setLoading(false);
      inFlight.current = false;
    }
  }, [runParams, recheckFyers]);

  const updateParam = <K extends keyof ScannerRunRequest>(key: K, val: ScannerRunRequest[K]) => {
    setRunParams((prev) => ({ ...prev, [key]: val }));
  };

  const updateSettingField = <K extends keyof ScannerSettings>(key: K, val: ScannerSettings[K]) => {
    setSettings((prev) => (prev ? { ...prev, [key]: val } : prev));
  };

  const saveSettings = useCallback(async () => {
    if (!settings) return;
    setSettingsSaving(true);
    setSettingsError(null);
    try {
      const saved = await updateScannerSettings(settings);
      setSettings(saved);
    } catch (e) {
      setSettingsError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSettingsSaving(false);
    }
  }, [settings]);

  return (
    <div className="min-h-screen bg-[#080B10]">
      {/* Nav bar */}
      <header className="border-b border-[#1A2540] bg-[#080B10] sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 bg-[#CF8B2E] rounded flex items-center justify-center">
              <TrendingUp size={14} className="text-[#080B10]" strokeWidth={2.5} />
            </div>
            <div>
              <div className="font-heading font-bold text-sm text-white tracking-tight leading-none">
                MTF AI Scanner
              </div>
              <div className="text-[9px] text-[#475569] font-heading uppercase tracking-widest mt-0.5">
                NSE Research
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {!USE_MOCK && backendStatus !== "down" && (
              <FyersStatusBadge status={fyers.status} unreachable={fyers.unreachable} />
            )}
            <div className="flex items-center gap-2">
              <ConnectionIndicator status={backendStatus} />
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-5 py-8">
        {/* Page header */}
        <div className="mb-8">
          <h1 className="font-heading font-bold text-3xl sm:text-4xl text-white tracking-tight">
            MTF AI Scanner
          </h1>
          <p className="text-[#64748B] mt-2 text-sm">
            Evidence-based 1–4 week MTF opportunities from the NSE universe
          </p>
        </div>

        {/* Backend unavailable banner */}
        {!USE_MOCK && backendStatus === "down" && (
          <div className="border border-[#4E1B1B] bg-[#2E1212] rounded-lg p-4 mb-6 flex items-start gap-3">
            <XCircle size={16} className="text-[#F05252] mt-0.5 shrink-0" />
            <p className="text-sm text-[#F05252] font-heading font-semibold">{BACKEND_UNAVAILABLE_MESSAGE}</p>
          </div>
        )}

        {/* Controls panel */}
        <div className="border border-[#1A2540] rounded-lg bg-[#0F1520] mb-8 overflow-hidden">
          <div className="p-5">
            <div className="flex flex-wrap items-end gap-4">
              {/* Capital */}
              <div className="flex-1 min-w-36">
                <label className="block text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1.5">
                  Available Capital
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[#64748B] font-data">₹</span>
                  <input
                    type="number"
                    value={runParams.available_capital}
                    onChange={(e) => updateParam("available_capital", Number(e.target.value))}
                    className="w-full bg-[#0B1018] border border-[#1A2540] rounded px-3 pl-7 py-2.5 text-sm font-data text-white focus:outline-none focus:border-[#CF8B2E] transition-colors"
                  />
                </div>
              </div>

              {/* Risk percent */}
              <div className="w-32">
                <label className="block text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1.5">
                  Risk %
                </label>
                <div className="relative">
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    max="5"
                    value={runParams.risk_percent}
                    onChange={(e) => updateParam("risk_percent", Number(e.target.value))}
                    className="w-full bg-[#0B1018] border border-[#1A2540] rounded px-3 py-2.5 text-sm font-data text-white focus:outline-none focus:border-[#CF8B2E] transition-colors pr-8"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-[#64748B] font-data">%</span>
                </div>
              </div>

              {/* Max positions */}
              <div className="w-32">
                <label className="block text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1.5">
                  Max Positions
                </label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={runParams.max_positions}
                  onChange={(e) => updateParam("max_positions", Number(e.target.value))}
                  className="w-full bg-[#0B1018] border border-[#1A2540] rounded px-3 py-2.5 text-sm font-data text-white focus:outline-none focus:border-[#CF8B2E] transition-colors"
                />
              </div>

              {/* Holding period */}
              <div className="w-36">
                <label className="block text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1.5">
                  Holding Period
                </label>
                <div className="relative">
                  <select
                    value={runParams.holding_period}
                    onChange={(e) => updateParam("holding_period", e.target.value)}
                    className="w-full appearance-none bg-[#0B1018] border border-[#1A2540] rounded px-3 py-2.5 text-sm font-heading text-white focus:outline-none focus:border-[#CF8B2E] transition-colors pr-8"
                  >
                    <option value="1-2 weeks">1–2 weeks</option>
                    <option value="1-4 weeks">1–4 weeks</option>
                    <option value="2-4 weeks">2–4 weeks</option>
                    <option value="3-6 weeks">3–6 weeks</option>
                  </select>
                  <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#475569] pointer-events-none" />
                </div>
              </div>

              {/* Run scan button */}
              <button
                onClick={handleScan}
                disabled={loading}
                className="flex items-center gap-2 px-6 py-2.5 bg-[#CF8B2E] hover:bg-[#E09D3E] disabled:opacity-50 disabled:cursor-not-allowed text-[#080B10] font-heading font-bold text-sm uppercase tracking-widest rounded transition-colors duration-200 shrink-0"
              >
                {loading ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Scanning…
                  </>
                ) : (
                  <>
                    <ScanLine size={14} />
                    Run Scan
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Settings drawer toggle */}
          <button
            className="w-full flex items-center gap-2 px-5 py-2.5 text-[10px] font-heading uppercase tracking-widest text-[#475569] hover:text-[#64748B] border-t border-[#1A2540] bg-[#0B1018] hover:bg-[#0D1220] transition-colors"
            onClick={() => setShowSettings((x) => !x)}
          >
            <Settings2 size={11} />
            Advanced Settings
            <ChevronDown size={11} className={`ml-auto transition-transform ${showSettings ? "rotate-180" : ""}`} />
          </button>

          {showSettings && (
            <div className="px-5 pb-5 border-t border-[#1A2540] pt-4">
              {settingsLoading && <p className="text-xs text-[#475569]">Loading settings…</p>}
              {settingsError && <p className="text-xs text-[#F05252] mb-3">{settingsError}</p>}
              {settings && (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div>
                      <label className="block text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1.5">
                        Min Price (₹)
                      </label>
                      <input
                        type="number"
                        value={settings.min_price}
                        onChange={(e) => updateSettingField("min_price", Number(e.target.value))}
                        className="w-full bg-[#0B1018] border border-[#1A2540] rounded px-3 py-2 text-sm font-data text-white focus:outline-none focus:border-[#CF8B2E] transition-colors"
                      />
                    </div>
                    <div>
                      <label className="block text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1.5">
                        Max Candidates
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={settings.max_candidates}
                        onChange={(e) => updateSettingField("max_candidates", Number(e.target.value))}
                        className="w-full bg-[#0B1018] border border-[#1A2540] rounded px-3 py-2 text-sm font-data text-white focus:outline-none focus:border-[#CF8B2E] transition-colors"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-xs text-[#94A3B8] font-heading mt-5">
                      <input
                        type="checkbox"
                        checked={settings.mtf_eligible_only}
                        onChange={(e) => updateSettingField("mtf_eligible_only", e.target.checked)}
                        className="accent-[#CF8B2E]"
                      />
                      MTF Eligible Only
                    </label>
                    <label className="flex items-center gap-2 text-xs text-[#94A3B8] font-heading mt-5">
                      <input
                        type="checkbox"
                        checked={settings.fno_only}
                        onChange={(e) => updateSettingField("fno_only", e.target.checked)}
                        className="accent-[#CF8B2E]"
                      />
                      F&O Stocks Only
                    </label>
                    <label className="flex items-center gap-2 text-xs text-[#94A3B8] font-heading">
                      <input
                        type="checkbox"
                        checked={settings.exclude_penny_stocks}
                        onChange={(e) => updateSettingField("exclude_penny_stocks", e.target.checked)}
                        className="accent-[#CF8B2E]"
                      />
                      Exclude Penny Stocks
                    </label>
                  </div>
                  <div className="flex items-center gap-3 mt-4">
                    <button
                      onClick={saveSettings}
                      disabled={settingsSaving}
                      className="px-4 py-1.5 text-xs font-heading font-semibold uppercase tracking-widest text-[#CF8B2E] border border-[#CF8B2E] rounded hover:bg-[#CF8B2E] hover:text-[#080B10] disabled:opacity-50 transition-colors"
                    >
                      {settingsSaving ? "Saving…" : "Save Settings"}
                    </button>
                    <p className="text-[10px] text-[#475569] leading-relaxed">
                      These filters run server-side before candidates are ranked.
                    </p>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Loading state */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-24 gap-5">
            <div className="relative">
              <div className="w-16 h-16 border-2 border-[#1A2540] rounded-full" />
              <div className="w-16 h-16 border-2 border-transparent border-t-[#CF8B2E] rounded-full animate-spin absolute top-0 left-0" />
            </div>
            <div className="text-center">
              <p className="font-heading font-semibold text-white text-sm">Scanning NSE Universe…</p>
              <p className="text-xs text-[#475569] mt-1">Analyzing candidates against MTF criteria</p>
            </div>
          </div>
        )}

        {/* FYERS session expired -- shown instead of a raw HTTP 401, or up
            front when the backend already knows the session is gone */}
        {!USE_MOCK && !loading && (fyersAuthError || fyers.status?.status === "REFRESH_REQUIRED" || fyers.status?.status === "LOGIN_REQUIRED") && (
          <div className="mb-6">
            <FyersAuthPrompt
              status={fyers.status}
              onReconnected={(s) => {
                fyers.setStatus(s);
                if (s.status === "CONNECTED") {
                  setFyersAuthError(false);
                  setError(null);
                }
              }}
            />
          </div>
        )}

        {/* Error state */}
        {error && !loading && !fyersAuthError && (
          <div className="border border-[#4E1B1B] bg-[#2E1212] rounded-lg p-5 flex items-start gap-3 mb-6">
            <AlertCircle size={16} className="text-[#F05252] mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-heading font-semibold text-[#F05252]">Scan Failed</p>
              <p className="text-xs text-[#94A3B8] mt-1">{error}</p>
            </div>
          </div>
        )}

        {/* Initial state — no scan yet */}
        {!loading && !error && !scanResult && (
          <div className="text-center py-24">
            <div className="w-16 h-16 border border-[#1A2540] rounded-full flex items-center justify-center mx-auto mb-5">
              <ScanLine size={24} className="text-[#CF8B2E]" />
            </div>
            <p className="font-heading font-semibold text-[#E2E8F0] text-sm">
              Configure your parameters and run a scan
            </p>
            <p className="text-xs text-[#475569] mt-2 max-w-xs mx-auto">
              The engine will analyze the NSE universe and surface the top MTF candidates ranked by evidence quality.
            </p>
          </div>
        )}

        {/* Results */}
        {!loading && scanResult && (
          <>
            {/* Scan meta */}
            <div className="flex flex-wrap items-center gap-5 mb-6 pb-5 border-b border-[#1A2540]">
              <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
                <Clock size={12} />
                <span className="font-heading uppercase tracking-wider">Generated</span>
                <span className="font-data text-[#94A3B8]">{formatTime(scanResult.generated_at)}</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
                <Database size={12} />
                <span className="font-heading uppercase tracking-wider">Analyzed</span>
                <span className="font-data text-[#94A3B8]">{scanResult.stocks_analyzed} stocks</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
                <span className="font-heading uppercase tracking-wider">Rejected</span>
                <span className="font-data text-[#94A3B8]">{scanResult.stocks_rejected}</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
                <span className="font-heading uppercase tracking-wider">Horizon</span>
                <span className="font-data text-[#94A3B8]">{scanResult.holding_period}</span>
              </div>
              <div className="ml-auto text-xs text-[#64748B] font-heading">
                {scanResult.candidates.length} candidate{scanResult.candidates.length !== 1 ? "s" : ""} found
              </div>
            </div>

            {scanResult.candidates.length === 0 ? (
              <div className="text-center py-16 border border-[#1A2540] rounded-lg bg-[#0F1520]">
                <p className="font-heading font-semibold text-[#64748B]">No MTF Candidates Found</p>
                <p className="text-xs text-[#475569] mt-2">
                  No stocks met the evidence threshold in the current market conditions. Consider adjusting your
                  advanced settings or risk parameters.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {scanResult.candidates.map((c, i) => (
                  <StockCard key={c.symbol} candidate={c} rank={i + 1} holdingPeriod={scanResult.holding_period} />
                ))}
              </div>
            )}

            {/* Disclaimer */}
            <p className="text-[10px] text-[#374151] text-center mt-8 leading-relaxed max-w-2xl mx-auto">
              MTF Setup Scores indicate evidence quality, not guaranteed returns. All signals are market-behaviour
              proxies. Past performance does not guarantee future results. This is a research tool — not a trading
              recommendation or financial advice. Always apply your own judgment and risk management.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
