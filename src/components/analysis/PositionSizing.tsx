import { PositionSizing } from "../../types/api";

function fmt(n: number) {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function Row({ label, value, valueClass = "text-[#E2E8F0]", sub }: { label: string; value: string; valueClass?: string; sub?: string }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-[#1A2540] last:border-b-0">
      <span className="text-xs text-[#64748B] font-heading">{label}</span>
      <div className="text-right">
        <span className={`font-data font-semibold text-sm ${valueClass}`}>{value}</span>
        {sub && <div className="text-[10px] text-[#475569] mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

export default function PositionSizingSection({ data }: { data: PositionSizing }) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">Position Sizing</h2>
        <p className="text-[10px] text-[#475569] mt-1">Calculated by backend risk engine · display only</p>
      </div>
      <div className="px-5 py-2">
        <Row label="Available Capital" value={fmt(data.available_capital)} />
        <Row label="Risk %" value={`${data.risk_percent}%`} sub={fmt(data.max_rupee_risk)} valueClass="text-[#F59E0B]" />
        <Row label="Entry Price" value={fmt(data.entry_price)} />
        <Row label="Invalidation" value={fmt(data.invalidation_price)} valueClass="text-[#F05252]" />
        <Row label="Risk Per Share" value={fmt(data.risk_per_share)} valueClass="text-[#F05252]" />
        <Row label="Calculated Quantity" value={`${data.quantity} shares`} valueClass="text-[#CF8B2E]" />
        <Row
          label="Capital Required"
          value={fmt(data.capital_required)}
          sub={`${data.capital_utilization_pct.toFixed(0)}% of available capital`}
        />
      </div>

      {data.notes.length > 0 && (
        <div className="px-5 pb-4 space-y-1.5">
          {data.notes.map((n, i) => (
            <p key={i} className="text-[10px] text-[#F59E0B] leading-relaxed">
              ⚠ {n}
            </p>
          ))}
        </div>
      )}

      {/* Capital bar */}
      <div className="px-5 pb-5">
        <div className="h-1.5 bg-[#1A2540] rounded-full overflow-hidden mt-1">
          <div
            className="h-full bg-[#CF8B2E] rounded-full transition-all duration-700"
            style={{ width: `${Math.min(data.capital_utilization_pct, 100)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1.5">
          <span className="text-[9px] text-[#475569] font-heading">Capital allocated</span>
          <span className="text-[9px] font-data text-[#CF8B2E]">{data.capital_utilization_pct.toFixed(0)}%</span>
        </div>
      </div>

      <div className="px-5 py-3 border-t border-[#1A2540] bg-[#0B1018]">
        <p className="text-[10px] text-[#475569] leading-relaxed">
          Position sizing is calculated by the backend engine based on your risk settings. Adjust available capital
          and risk per trade in the scanner to recalculate.
        </p>
      </div>
    </section>
  );
}
