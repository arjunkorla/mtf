import { SectorData } from "../../types/stock";
import Badge from "../ui/Badge";
import DataUnavailable from "../ui/DataUnavailable";

const RS_STYLES: Record<string, { variant: "positive" | "negative" | "neutral" | "muted"; label: string }> = {
  OUTPERFORM: { variant: "positive", label: "Outperforming" },
  UNDERPERFORM: { variant: "negative", label: "Underperforming" },
  NEUTRAL: { variant: "neutral", label: "Neutral" },
  INSUFFICIENT_DATA: { variant: "muted", label: "Insufficient Data" },
};

const SECTOR_STYLES: Record<string, { variant: "positive" | "negative" | "neutral" }> = {
  STRONG: { variant: "positive" },
  WEAK: { variant: "negative" },
  NEUTRAL: { variant: "neutral" },
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1A2540] last:border-b-0">
      <span className="text-xs text-[#64748B] font-heading">{label}</span>
      <div>{children}</div>
    </div>
  );
}

export default function SectorRelativeStrengthSection({ data }: { data: SectorData }) {
  const rs = RS_STYLES[data.relative_strength.label];

  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">
          Sector & Relative Strength
        </h2>
        <p className="text-[10px] text-[#475569] mt-1">
          A strong stock in a weak sector is treated differently from a strong stock in a strong sector
        </p>
      </div>
      <div className="px-5 py-2">
        <Row label="Sector">
          <span className="font-data text-sm text-[#E2E8F0]">{data.sector_name ?? <DataUnavailable />}</span>
        </Row>
        <Row label="Sector Strength">
          {data.sector_strength_label ? (
            <Badge variant={SECTOR_STYLES[data.sector_strength_label]?.variant ?? "neutral"}>{data.sector_strength_label}</Badge>
          ) : (
            <DataUnavailable />
          )}
        </Row>
        <Row label="Market Regime">
          {data.market_regime && data.market_regime !== "INSUFFICIENT_DATA" ? (
            <Badge variant={data.market_regime === "RISK_ON" ? "positive" : data.market_regime === "RISK_OFF" ? "negative" : "neutral"}>
              {data.market_regime.replace(/_/g, " ")}
            </Badge>
          ) : (
            <DataUnavailable />
          )}
        </Row>
        <Row label="Relative Strength vs NIFTY">
          <div className="flex items-center gap-2">
            {data.relative_strength.vs_nifty_pct_20d !== null && (
              <span className="font-data text-sm text-[#E2E8F0]">
                {data.relative_strength.vs_nifty_pct_20d >= 0 ? "+" : ""}
                {data.relative_strength.vs_nifty_pct_20d.toFixed(2)}% (20D)
              </span>
            )}
            <Badge variant={rs.variant}>{rs.label}</Badge>
          </div>
        </Row>
        <Row label="Relative Strength vs Sector">
          {data.relative_strength.vs_sector_pct_20d !== null ? (
            <span className="font-data text-sm text-[#E2E8F0]">
              {data.relative_strength.vs_sector_pct_20d >= 0 ? "+" : ""}
              {data.relative_strength.vs_sector_pct_20d.toFixed(2)}% (20D)
            </span>
          ) : (
            <DataUnavailable />
          )}
        </Row>
      </div>
    </section>
  );
}
