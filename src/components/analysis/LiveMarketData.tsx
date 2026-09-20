import { useEffect, useRef, useState } from "react";
import { getLiveQuote, getMarketDepth } from "../../api/marketDataApi";
import { LiveMarketDataResponse } from "../../types/marketData";
import Badge from "../ui/Badge";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

const QUOTE_POLL_MS = 5000; // /market/live is a cheap Redis-only read
const DEPTH_POLL_MS = 15000; // /market/depth can incur a live FYERS call; matches its own cache TTL

function statusVariant(status: LiveMarketDataResponse["status"]) {
  if (status === "LIVE") return "positive" as const;
  if (status === "STALE") return "warning" as const;
  return "muted" as const;
}

function fmtPrice(n: number | null) {
  return n === null ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function fmtQty(n: number | null) {
  return n === null ? "—" : n.toLocaleString("en-IN");
}

/** Small, evidence-only confirmation panel -- LTP/volume from the shared
 * backend WebSocket hub, plus a 5-level depth ladder from a cached REST
 * fetch. Purely a confirmation layer for the scanner's own score; this
 * never claims depth reflects institutional intent (section 9 rule), it
 * only displays the raw bid/ask ladder FYERS actually returned. */
export default function LiveMarketData({ symbol }: { symbol: string }) {
  const [quote, setQuote] = useState<LiveMarketDataResponse | null>(null);
  const [depth, setDepth] = useState<LiveMarketDataResponse | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    if (USE_MOCK) return;
    mountedRef.current = true;

    const pollQuote = () => {
      getLiveQuote(symbol)
        .then((data) => mountedRef.current && setQuote(data))
        .catch(() => mountedRef.current && setQuote(null));
    };
    const pollDepth = () => {
      getMarketDepth(symbol)
        .then((data) => mountedRef.current && setDepth(data))
        .catch(() => mountedRef.current && setDepth(null));
    };

    pollQuote();
    pollDepth();
    const quoteTimer = setInterval(pollQuote, QUOTE_POLL_MS);
    const depthTimer = setInterval(pollDepth, DEPTH_POLL_MS);

    return () => {
      mountedRef.current = false;
      clearInterval(quoteTimer);
      clearInterval(depthTimer);
    };
  }, [symbol]);

  if (USE_MOCK) return null; // no mock path for live data -- show nothing rather than fake it
  if (!quote || quote.status === "UNAVAILABLE") return null; // no live data yet -- don't clutter the page

  const bidLevels = depth?.depth?.bid_levels ?? [];
  const askLevels = depth?.depth?.ask_levels ?? [];
  const hasDepth = depth?.status !== "UNAVAILABLE" && (bidLevels.length > 0 || askLevels.length > 0);

  return (
    <div className="border border-[#1A2540] rounded-lg bg-[#0F1520] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-heading uppercase tracking-widest text-[#475569]">Live Market Data</span>
          <Badge variant={statusVariant(quote.status)}>{quote.status}</Badge>
        </div>
        {quote.quote && (
          <div className="flex items-baseline gap-3">
            <span className="font-data font-bold text-lg text-white">₹{fmtPrice(quote.quote.ltp)}</span>
            {quote.quote.volume !== null && (
              <span className="text-[11px] font-data text-[#64748B]">Vol {fmtQty(quote.quote.volume)}</span>
            )}
          </div>
        )}
      </div>

      {hasDepth && (
        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-[#1A2540]">
          <div>
            <div className="text-[9px] font-heading uppercase tracking-widest text-[#22C9B4] mb-1.5">Bid</div>
            <div className="space-y-1">
              {bidLevels.slice(0, 5).map((lvl, i) => (
                <div key={i} className="flex items-center justify-between text-[11px] font-data">
                  <span className="text-[#64748B]">{fmtQty(lvl.quantity)}</span>
                  <span className="text-[#22C9B4]">{fmtPrice(lvl.price)}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[9px] font-heading uppercase tracking-widest text-[#F05252] mb-1.5 text-right">Ask</div>
            <div className="space-y-1">
              {askLevels.slice(0, 5).map((lvl, i) => (
                <div key={i} className="flex items-center justify-between text-[11px] font-data">
                  <span className="text-[#F05252]">{fmtPrice(lvl.price)}</span>
                  <span className="text-[#64748B]">{fmtQty(lvl.quantity)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
