import { FundamentalData } from "../../types/stock";
import DataUnavailable from "../ui/DataUnavailable";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1A2540] last:border-b-0">
      <span className="text-xs text-[#64748B] font-heading">{label}</span>
      <div className="font-data text-sm text-[#E2E8F0]">{children}</div>
    </div>
  );
}

function pct(n: number | null) {
  return n !== null ? <span className={n >= 0 ? "text-[#22C9B4]" : "text-[#F05252]"}>{n >= 0 ? "+" : ""}{n.toFixed(1)}%</span> : <DataUnavailable />;
}

function num(n: number | null, suffix = "") {
  return n !== null ? `${n.toFixed(2)}${suffix}` : <DataUnavailable />;
}

export default function FundamentalsSection({ data }: { data: FundamentalData }) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">Fundamentals</h2>
        <p className="text-[10px] text-[#475569] mt-1">Validated fundamental data -- never inferred from price</p>
      </div>

      {!data.is_available ? (
        <div className="px-5 py-6">
          <DataUnavailable label="No validated fundamentals on file for this stock" />
        </div>
      ) : (
        <div className="px-5 py-2">
          <Row label="Revenue Growth (YoY)">{pct(data.revenue_growth_yoy_pct)}</Row>
          <Row label="Profit Growth (YoY)">{pct(data.profit_growth_yoy_pct)}</Row>
          <Row label="EPS">{num(data.eps)}</Row>
          <Row label="Net Margin">{pct(data.net_margin_pct)}</Row>
          <Row label="Debt / Equity">{num(data.debt_to_equity)}</Row>
          <Row label="ROE">{pct(data.roe_pct)}</Row>
          <Row label="ROCE">{pct(data.roce_pct)}</Row>
          <Row label="P/E Ratio">{num(data.pe_ratio)}</Row>
        </div>
      )}
    </section>
  );
}
