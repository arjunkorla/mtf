/** Mirrors backend/app/schemas/market_data.py (LiveMarketDataResponse). */

export interface LiveQuoteData {
  ltp: number;
  volume: number | null;
}

export interface DepthLevel {
  price: number | null;
  quantity: number | null;
  order_count: number | null;
}

export interface MarketDepthData {
  top_bid: number | null;
  top_ask: number | null;
  spread: number | null;
  total_buy_qty: number | null;
  total_sell_qty: number | null;
  bid_levels: DepthLevel[];
  ask_levels: DepthLevel[];
}

export type MarketDataStatus = "LIVE" | "STALE" | "UNAVAILABLE";

export interface LiveMarketDataResponse {
  symbol: string;
  source: string;
  timestamp: string | null;
  status: MarketDataStatus;
  is_stale: boolean;
  quote: LiveQuoteData | null;
  depth: MarketDepthData | null;
}
