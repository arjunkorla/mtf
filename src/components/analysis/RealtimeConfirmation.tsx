import { useEffect, useState } from "react";
import { CheckCircle2, MinusCircle, AlertTriangle, XCircle } from "lucide-react";
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

/** One line item: available signals get a check/dash based on whether they
 * lean supportive; unavailable ones show plainly as unavailable -- never a
 * fabricated checkmark. */
function Row({ ok, label }: { ok: boolean | null; label: string }) {
  const Icon = ok === true ? CheckCircle2 : ok === false ? MinusCircle : XCircle;
  const color = ok === true ? "text-[#22C9B4]" : ok === false ? "text-[#64748B]" : "text-[#374151]";
  return (
    <div className="flex items-center gap-2 text-xs">
      <Icon size={13} className={`shrink-0 ${color}`} />
      <span className={ok === null ? "text-[#475569]" : "text-[#CBD5E1]"}>{label}</span>
    </div>
  );
}

/** Real-Time Confirmation panel -- evidence-based intraday read on the
 * existing MTF setup, kept visually and numerically separate from the MTF
 * structural score (never combined into one number). Fetched once on
 * mount, not polled (this is a point-in-time confirmation check, not a
 * streaming ticker). */
export default function RealtimeConfirmation({ symbol }: { symbol: string }) {
  const [data, setData] = useState<RealtimeConfirmationResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (USE_MOCK) return;
    getRealtimeConfirmation(symbol)
      .then(setData)
      .catch(() => setError(true));
  }, [symbol]);

  if (USE_MOCK || error || !data) return null;

  const rows: { ok: boolean | null; label: string }[] = [
    {
      ok: data.price_confirmation.status === "ABOVE_ENTRY_ZONE" || data.price_confirmation.status === "INSIDE_ENTRY_ZONE"
        ? true : data.price_confirmation.status === "UNAVAILABLE" ? null : false,
      label: `Price ${data.price_confirmation.status.replace(/_/g, " ").toLowerCase()}`,
    },
    {
      // Precise wording on purpose: this is the daily-bar volume_ratio
      // (latest completed session vs its 20-day average), never true
      // intraday volume -- see VolumeConfirmationData.baseline.
      ok: data.volume_confirmation.status === "EXPANDING" ? true : data.volume_confirmation.status === "INSUFFICIENT_DATA" ? null : false,
      label:
        data.volume_confirmation.status === "INSUFFICIENT_DATA"
          ? "Daily volume ratio unavailable"
          : `Daily volume ratio: ${data.volume_confirmation.status.toLowerCase()} (latest session vs 20D avg)`,
    },
    {
      ok: data.vwap_confirmation.status === "ABOVE_VWAP" ? true : data.vwap_confirmation.status === "UNAVAILABLE" ? null : false,
      label: data.vwap_confirmation.status === "UNAVAILABLE" ? "VWAP unavailable (no intraday VWAP source yet)" : data.vwap_confirmation.status.replace(/_/g, " ").toLowerCase(),
    },
    {
      ok: data.depth_confirmation.status === "STRONG_BID" || data.depth_confirmation.status === "MODERATE_BID"
        ? true : data.depth_confirmation.status === "UNAVAILABLE" ? null : false,
      label: `Depth ${data.depth_confirmation.status.replace(/_/g, " ").toLowerCase()}`,
    },
    {
      ok: data.futures_confirmation.status.startsWith("PRICE_UP") ? true : data.futures_confirmation.status === "UNAVAILABLE" ? null : false,
      label: `Futures ${data.futures_confirmation.status.replace(/_/g, " ").toLowerCase()}`,
    },
    {
      ok: data.persistence.status === "STRENGTHENING" || data.persistence.status === "PERSISTED"
        ? true : data.persistence.status === "INSUFFICIENT_OBSERVATIONS" ? null : false,
      label: `Condition ${data.persistence.status.replace(/_/g, " ").toLowerCase()}`,
    },
  ];

  return (
    <div className="border border-[#1A2540] rounded-lg bg-[#0F1520] p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] font-heading uppercase tracking-widest text-[#475569]">
          Real-Time Confirmation
        </div>
        {data.market_status === "MARKET_CLOSED_LAST_AVAILABLE" && (
          <Badge variant="warning">Market Closed — Last Available</Badge>
        )}
      </div>

      <div className="flex items-center justify-between mb-3">
        <Badge variant={statusVariant(data.confirmation_status)} size="md">
          {data.confirmation_status.replace(/_/g, " ")}
        </Badge>
        <div className="text-right">
          {data.confirmation_score !== null && (
            <div className="font-data font-bold text-lg text-white">{data.confirmation_score.toFixed(0)}</div>
          )}
          <div className="text-[9px] font-heading uppercase tracking-widest text-[#475569]">
            Data Quality: {data.data_quality}
          </div>
        </div>
      </div>

      <div className="space-y-1.5 pt-3 border-t border-[#1A2540]">
        {rows.map((r, i) => (
          <Row key={i} ok={r.ok} label={r.label} />
        ))}
      </div>

      {data.warnings.length > 0 && (
        <div className="mt-3 pt-3 border-t border-[#1A2540] space-y-1.5">
          {data.warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-[10px] text-[#94A3B8]">
              <AlertTriangle size={11} className="shrink-0 mt-0.5 text-[#F59E0B]" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      <p className="text-[9px] text-[#374151] mt-3 pt-3 border-t border-[#1A2540] leading-relaxed">
        This is a separate confirmation reading of current intraday evidence -- it does not change the MTF
        structural score above and is not a prediction of future price movement.
      </p>
    </div>
  );
}
