import { StockAnalysisResponse, StockSummary } from "../types/stock";
import { PositionSizeRequest, PositionSizeResponse } from "../types/api";
import { getMockAnalysis } from "../mock/stockAnalysisData";
import { client } from "./client";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

/** GET /api/stocks/{symbol}/analysis -- full candidate + AI research note.
 * Returns null only when the stock genuinely isn't in the configured
 * universe (404); any other failure propagates as an ApiError. */
export async function getStockAnalysis(symbol: string): Promise<StockAnalysisResponse | null> {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 800));
    return getMockAnalysis(symbol);
  }
  try {
    return await client.get<StockAnalysisResponse>(`/stocks/${encodeURIComponent(symbol)}/analysis`);
  } catch (err) {
    if (err && typeof err === "object" && "status" in err && (err as { status?: number }).status === 404) {
      return null;
    }
    throw err;
  }
}

/** GET /api/stocks/{symbol} -- lightweight summary (universe membership). */
export function getStock(symbol: string): Promise<StockSummary> {
  return client.get<StockSummary>(`/stocks/${encodeURIComponent(symbol)}`);
}

/** POST /api/position-size -- the backend's risk_engine is the only place
 * quantity/risk math happens; this just forwards inputs and returns its
 * result untouched. */
export function computePositionSize(request: PositionSizeRequest): Promise<PositionSizeResponse> {
  return client.post<PositionSizeResponse>("/position-size", request);
}
