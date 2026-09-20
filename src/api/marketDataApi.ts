import { LiveMarketDataResponse } from "../types/marketData";
import { client } from "./client";

/** GET /api/market/live/{symbol} -- Redis-only read of whatever the shared
 * backend WebSocket hub last cached; cheap enough to poll frequently. */
export function getLiveQuote(symbol: string): Promise<LiveMarketDataResponse> {
  return client.get<LiveMarketDataResponse>(`/market/live/${encodeURIComponent(symbol)}`);
}

/** GET /api/market/depth/{symbol} -- short-TTL-cached REST fetch; poll less
 * frequently than the quote endpoint since it can incur a live FYERS call. */
export function getMarketDepth(symbol: string): Promise<LiveMarketDataResponse> {
  return client.get<LiveMarketDataResponse>(`/market/depth/${encodeURIComponent(symbol)}`);
}
