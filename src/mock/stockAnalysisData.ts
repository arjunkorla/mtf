/**
 * Mock data for GET /stocks/{symbol}/analysis, used only when
 * VITE_USE_MOCK_DATA=true. Shaped exactly like StockAnalysisResponse.
 */
import { StockAnalysisResponse } from "../types/stock";
import { candidate, MOCK_SCANNER_RESPONSE } from "./scannerData";

const RELIANCE_ANALYSIS: StockAnalysisResponse = {
  symbol: "NSE:RELIANCE-EQ",
  company_name: "Reliance Industries Ltd",
  market_data: {
    price: 3705.85,
    change_pct: 0.64,
    volume: 5432100,
    avg_volume_20d: null,
    day_high: 3720.0,
    day_low: 3680.0,
    week_52_high: null,
    week_52_low: null,
    as_of: new Date().toISOString(),
  },
  candidate: candidate({
    symbol: "NSE:RELIANCE-EQ",
    company_name: "Reliance Industries Ltd",
    ai_research: {
      sections: {
        "WHY WAS THIS STOCK SELECTED?":
          "RELIANCE scored 62.9/100 with a BREAKOUT_RETEST setup in a STRONG_UPTREND, supported by 8 available score components out of 8.",
        "STRONGEST EVIDENCE": "Price is within 3% of the 20D high, a potential breakout/retest zone.",
        "CONFLICTING EVIDENCE": "RSI14 at 80.1, elevated extension risk.",
        "INSTITUTIONAL FOOTPRINT PROXY": "Institutional Footprint Proxy: NEUTRAL (score 50.9/100), based on 3 available proxies.",
        "KEY RISKS": "RSI is in overbought territory -- pullback risk is elevated. Fundamental data is unavailable for this stock.",
        "WHAT WOULD CONFIRM THE SETUP?": "A daily close above the 20D high on volume at or above 1.5x the 20-day average.",
        "WHAT WOULD INVALIDATE IT?": "Daily close below 3348.61 (support/EMA structure).",
        "POSITION SIZING EXPLANATION": "Max rupee risk 2000 (2% of 100000 capital) / risk per share 375.12 = 5 shares, capital required 18529.25.",
      },
      raw_text: null,
      flagged_unverified_numbers: [],
    },
  }),
  ai_research: null,
};

const MOCK_ANALYSES: Record<string, StockAnalysisResponse> = {
  "NSE:RELIANCE-EQ": RELIANCE_ANALYSIS,
};

/** Matches on the full FYERS-style symbol or the bare ticker (e.g. "RELIANCE"). */
export function getMockAnalysis(symbol: string): StockAnalysisResponse | null {
  const direct = MOCK_ANALYSES[symbol];
  if (direct) return direct;

  const ticker = symbol.toUpperCase().replace(/^NSE:/, "").replace(/-EQ$/, "");
  const bySymbol = Object.values(MOCK_ANALYSES).find(
    (a) => a.symbol.toUpperCase().replace(/^NSE:/, "").replace(/-EQ$/, "") === ticker,
  );
  if (bySymbol) return bySymbol;

  const scanCandidate = MOCK_SCANNER_RESPONSE.candidates.find(
    (c) => c.symbol.toUpperCase().replace(/^NSE:/, "").replace(/-EQ$/, "") === ticker,
  );
  if (!scanCandidate) return null;

  return {
    symbol: scanCandidate.symbol,
    company_name: scanCandidate.company_name,
    market_data: {
      price: scanCandidate.price,
      change_pct: null,
      volume: null,
      avg_volume_20d: null,
      day_high: null,
      day_low: null,
      week_52_high: null,
      week_52_low: null,
      as_of: new Date().toISOString(),
    },
    candidate: scanCandidate,
    ai_research: null,
  };
}
