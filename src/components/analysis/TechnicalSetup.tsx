import { TechnicalData, VolumeData } from "../../types/stock";
import { RadarChart, PolarGrid, PolarAngleAxis, Radar, ResponsiveContainer, Tooltip } from "recharts";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import DataUnavailable from "../ui/DataUnavailable";

function fmt(n: number | null) {
  if (n === null) return null;
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

const TREND_STYLES: Record<TechnicalData["trend_structure"], { color: string; label: string }> = {
  STRONG_UPTREND: { color: "#22C9B4", label: "Strong Uptrend" },
  UPTREND: { color: "#22C9B4", label: "Uptrend" },
  RANGE_BOUND: { color: "#64748B", label: "Range Bound" },
  DOWNTREND: { color: "#F05252", label: "Downtrend" },
  STRONG_DOWNTREND: { color: "#F05252", label: "Strong Downtrend" },
  INSUFFICIENT_DATA: { color: "#475569", label: "Insufficient Data" },
};

function TrendIcon({ trend }: { trend: TechnicalData["trend_structure"] }) {
  if (trend === "STRONG_UPTREND" || trend === "UPTREND") return <TrendingUp size={14} className="text-[#22C9B4]" />;
  if (trend === "STRONG_DOWNTREND" || trend === "DOWNTREND") return <TrendingDown size={14} className="text-[#F05252]" />;
  return <Minus size={14} className="text-[#64748B]" />;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1A2540] last:border-b-0">
      <span className="text-xs text-[#64748B] font-heading">{label}</span>
      <div className="flex items-center gap-2 font-data text-sm text-[#E2E8F0]">{children}</div>
    </div>
  );
}

function buildRadarData(t: TechnicalData, volumeRatio: number | null) {
  if (t.trend_structure === "INSUFFICIENT_DATA") return null;
  const trendScore = t.trend_structure.includes("STRONG_UPTREND") ? 95 : t.trend_structure === "UPTREND" ? 75 : t.trend_structure === "RANGE_BOUND" ? 50 : 15;
  return [
    { subject: "Trend", value: trendScore },
    { subject: "RSI", value: t.rsi_14 !== null ? Math.min(t.rsi_14, 100) : 0 },
    { subject: "ADX", value: t.adx_14 !== null ? Math.min(t.adx_14 * 2.5, 100) : 0 },
    { subject: "Volume", value: volumeRatio !== null ? Math.min(volumeRatio * 40, 100) : 0 },
    { subject: "Breakout", value: t.breakout_status === "BREAKOUT" ? 90 : t.breakout_status === "APPROACHING_BREAKOUT" ? 55 : 15 },
  ];
}

export default function TechnicalSetupSection({ data, volume }: { data: TechnicalData; volume: VolumeData }) {
  const radarData = buildRadarData(data, volume.volume_ratio);
  const trendStyle = TREND_STYLES[data.trend_structure];

  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">Technical Setup</h2>
        <p className="text-[10px] text-[#475569] mt-1">Key technical indicators for the MTF holding horizon</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 divide-y lg:divide-y-0 lg:divide-x divide-[#1A2540]">
        {/* Left: metrics */}
        <div className="px-5 py-2">
          <Row label="Trend">
            <TrendIcon trend={data.trend_structure} />
            <span className="font-heading font-semibold text-sm" style={{ color: trendStyle.color }}>
              {trendStyle.label}
            </span>
          </Row>
          <Row label="EMA 20">{fmt(data.ema_20) ?? <DataUnavailable />}</Row>
          <Row label="EMA 50">{fmt(data.ema_50) ?? <DataUnavailable />}</Row>
          <Row label="EMA 200">{fmt(data.ema_200) ?? <DataUnavailable />}</Row>
          <Row label="RSI (14)">
            {data.rsi_14 !== null ? (
              <span className={data.rsi_14 > 70 ? "text-[#F05252]" : data.rsi_14 < 40 ? "text-[#64748B]" : "text-[#22C9B4]"}>
                {data.rsi_14.toFixed(1)}
              </span>
            ) : (
              <DataUnavailable />
            )}
          </Row>
          <Row label="ADX (14)">{data.adx_14 !== null ? data.adx_14.toFixed(1) : <DataUnavailable />}</Row>
          <Row label="ATR (14)">{fmt(data.atr_14) ?? <DataUnavailable />}</Row>
          <Row label="Volume Ratio">
            {volume.volume_ratio !== null ? (
              <span className={volume.volume_ratio >= 1.5 ? "text-[#22C9B4]" : "text-[#E2E8F0]"}>
                {volume.volume_ratio.toFixed(2)}×
              </span>
            ) : (
              <DataUnavailable />
            )}
          </Row>
          <Row label="Breakout Status">
            <span
              className={
                data.breakout_status === "BREAKOUT"
                  ? "text-[#22C9B4]"
                  : data.breakout_status === "APPROACHING_BREAKOUT"
                  ? "text-[#CF8B2E]"
                  : "text-[#64748B]"
              }
            >
              {data.breakout_status.replace(/_/g, " ")}
            </span>
          </Row>
          <Row label="Support">{fmt(data.support_level) ?? <DataUnavailable />}</Row>
          <Row label="Resistance">{fmt(data.resistance_level) ?? <DataUnavailable />}</Row>
        </div>

        {/* Right: radar */}
        <div className="flex flex-col items-center justify-center p-5">
          {radarData ? (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#1A2540" />
                  <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: "#64748B", fontFamily: "Instrument Sans" }} />
                  <Radar dataKey="value" stroke="#CF8B2E" fill="#CF8B2E" fillOpacity={0.15} strokeWidth={1.5} />
                  <Tooltip
                    contentStyle={{
                      background: "#0F1520",
                      border: "1px solid #1A2540",
                      borderRadius: 4,
                      fontSize: 11,
                      fontFamily: "JetBrains Mono",
                      color: "#E2E8F0",
                    }}
                  />
                </RadarChart>
              </ResponsiveContainer>
              <p className="text-[9px] text-[#475569] font-heading uppercase tracking-wider mt-1">
                Technical Signal Radar
              </p>
            </>
          ) : (
            <DataUnavailable label="Insufficient price history for a technical radar" />
          )}
        </div>
      </div>
    </section>
  );
}
