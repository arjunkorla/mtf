import { AlertTriangle, XCircle } from "lucide-react";

interface Props {
  risks: string[];
  invalidationCondition: string | null;
}

export default function RiskAnalysisSection({ risks, invalidationCondition }: Props) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">
          What Could Go Wrong?
        </h2>
        <p className="text-[10px] text-[#475569] mt-1">Detected risks for this setup</p>
      </div>

      <div className="px-5 py-3 space-y-2.5">
        {risks.length === 0 ? (
          <p className="text-xs text-[#475569]">No risks were flagged for this candidate.</p>
        ) : (
          risks.map((risk, i) => (
            <div key={i} className="flex items-start gap-3">
              <AlertTriangle size={13} className="text-[#F59E0B] mt-0.5 shrink-0" />
              <span className="text-sm text-[#E2E8F0]">{risk}</span>
            </div>
          ))
        )}
      </div>

      {/* Invalidation */}
      <div className="mx-5 mb-5 mt-3 border border-[#4E1B1B] bg-[#200E0E] rounded-lg p-4">
        <div className="flex items-center gap-1.5 mb-2">
          <XCircle size={12} className="text-[#F05252]" />
          <span className="text-[10px] font-heading font-semibold uppercase tracking-widest text-[#F05252]">
            Invalidation Conditions
          </span>
        </div>
        <p className="text-xs text-[#94A3B8] leading-relaxed">
          {invalidationCondition ?? "Not determined -- insufficient technical data to define an invalidation level."}
        </p>
      </div>
    </section>
  );
}
