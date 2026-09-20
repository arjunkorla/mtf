import { FnoData, FnoPositioningProxy } from "../../types/stock";
import EvidenceList from "../ui/EvidenceList";
import DataUnavailable from "../ui/DataUnavailable";

const POSITIONING_LABELS: Record<FnoPositioningProxy, string> = {
  LONG_BUILDUP_PROXY: "Long-buildup proxy",
  SHORT_BUILDUP_PROXY: "Short-buildup proxy",
  SHORT_COVERING_PROXY: "Short-covering proxy",
  LONG_UNWINDING_PROXY: "Long-unwinding proxy",
  NEUTRAL: "Neutral",
  NOT_AVAILABLE: "Not available",
};

const POSITIONING_COLORS: Record<FnoPositioningProxy, string> = {
  LONG_BUILDUP_PROXY: "text-[#22C9B4]",
  SHORT_BUILDUP_PROXY: "text-[#F05252]",
  SHORT_COVERING_PROXY: "text-[#F59E0B]",
  LONG_UNWINDING_PROXY: "text-[#F59E0B]",
  NEUTRAL: "text-[#64748B]",
  NOT_AVAILABLE: "text-[#475569]",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1A2540] last:border-b-0">
      <span className="text-xs text-[#64748B] font-heading">{label}</span>
      <div>{children}</div>
    </div>
  );
}

export default function FOAnalysisSection({ data }: { data: FnoData }) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">F&O Positioning</h2>
        <p className="text-[10px] text-[#475569] mt-1">
          Futures & Options data as observable market-behaviour proxies
        </p>
      </div>

      {!data.is_available ? (
        <div className="px-5 py-6">
          <DataUnavailable label="F&O data not available -- not an F&O stock, or the feed is missing" />
        </div>
      ) : (
        <>
          <div className="px-5 py-2">
            <Row label="Positioning Proxy">
              <span className={`font-heading text-sm font-medium ${POSITIONING_COLORS[data.positioning_proxy]}`}>
                {POSITIONING_LABELS[data.positioning_proxy]}
              </span>
            </Row>
            <Row label="Futures Price Change">
              {data.futures_price_change_pct !== null ? (
                <span className={`font-data text-sm ${data.futures_price_change_pct >= 0 ? "text-[#22C9B4]" : "text-[#F05252]"}`}>
                  {data.futures_price_change_pct >= 0 ? "+" : ""}
                  {data.futures_price_change_pct.toFixed(2)}%
                </span>
              ) : (
                <DataUnavailable />
              )}
            </Row>
            <Row label="Futures OI Change">
              {data.futures_oi_change_pct !== null ? (
                <span className={`font-data text-sm ${data.futures_oi_change_pct >= 0 ? "text-[#22C9B4]" : "text-[#F05252]"}`}>
                  {data.futures_oi_change_pct >= 0 ? "+" : ""}
                  {data.futures_oi_change_pct.toFixed(2)}%
                </span>
              ) : (
                <DataUnavailable />
              )}
            </Row>
            <Row label="Put / Call OI Ratio">
              {data.put_call_oi_ratio !== null ? (
                <span className="font-data text-sm text-[#E2E8F0]">{data.put_call_oi_ratio.toFixed(2)}</span>
              ) : (
                <DataUnavailable />
              )}
            </Row>
          </div>
          {data.evidence.length > 0 && (
            <div className="px-5 py-4 border-t border-[#1A2540]">
              <EvidenceList items={data.evidence} />
            </div>
          )}
        </>
      )}

      <div className="px-5 py-3 border-t border-[#1A2540] bg-[#0B1018]">
        <p className="text-[10px] text-[#475569] leading-relaxed">
          F&O positioning data reflects aggregate open interest changes. Trader identity cannot be determined. Never
          interpret OI expansion as confirmed institutional activity.
        </p>
      </div>
    </section>
  );
}
