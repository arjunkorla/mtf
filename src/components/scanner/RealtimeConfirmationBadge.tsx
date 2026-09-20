import { useEffect, useState } from "react";
import { getRealtimeConfirmation } from "../../api/confirmationApi";
import { RealtimeConfirmationResponse } from "../../types/confirmation";
import Badge from "../ui/Badge";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

function statusVariant(status: RealtimeConfirmationResponse["confirmation_status"]) {
  if (status === "STRONGLY_SUPPORTIVE" || status === "SUPPORTIVE") return "positive" as const;
  if (status === "CONTRADICTORY") return "negative" as const;
  if (status === "NEUTRAL") return "neutral" as const;
  return "muted" as const;
}

/** Compact, lazily-fetched confirmation readout for one scanner candidate.
 * Only mounted when a card is expanded (see StockCard.tsx) -- never
 * fetched for all scanned candidates automatically, so a scan run never
 * incurs extra FYERS/depth load for symbols the user never looks at. Does
 * not affect ranking, selection, or the MTF score shown elsewhere on the
 * card -- purely an additional, separate read. */
export default function RealtimeConfirmationBadge({ symbol }: { symbol: string }) {
  const [data, setData] = useState<RealtimeConfirmationResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (USE_MOCK) return;
    let cancelled = false;
    getRealtimeConfirmation(symbol)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  if (USE_MOCK || error || !data) return null;

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-[10px] font-heading uppercase tracking-widest text-[#475569]">Real-Time</span>
      <Badge variant={statusVariant(data.confirmation_status)}>{data.confirmation_status.replace(/_/g, " ")}</Badge>
      {data.confirmation_score !== null && (
        <span className="font-data text-[#94A3B8]">{data.confirmation_score.toFixed(0)}</span>
      )}
      <span className="text-[10px] text-[#475569]">Data Quality {data.data_quality}</span>
    </div>
  );
}
