import { InstitutionalFootprint as IFP } from "../../types/api";
import { StrengthBadge } from "../ui/Badge";
import EvidenceList from "../ui/EvidenceList";
import { Info } from "lucide-react";

interface Props {
  data: IFP;
}

export default function InstitutionalFootprintSection({ data }: Props) {
  const insufficient = data.institutional_footprint_level === "INSUFFICIENT_DATA";

  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540] flex items-center justify-between">
        <div>
          <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">
            Institutional Footprint Proxy
          </h2>
          <div className="mt-1 flex items-center gap-2">
            <StrengthBadge strength={data.institutional_footprint_level} />
            {data.institutional_footprint_score !== null && (
              <span className="font-data text-xs text-[#64748B]">{data.institutional_footprint_score.toFixed(1)}/100</span>
            )}
          </div>
        </div>
      </div>

      <div className="px-5 py-4">
        {insufficient ? (
          <p className="text-xs text-[#475569] italic">
            Insufficient data to compute an institutional footprint proxy for this stock.
          </p>
        ) : (
          <EvidenceList items={data.evidence} />
        )}
      </div>

      <div className="px-5 py-3 border-t border-[#1A2540] flex items-start gap-2 bg-[#0B1018]">
        <Info size={11} className="text-[#475569] mt-0.5 shrink-0" />
        <p className="text-[10px] text-[#475569] leading-relaxed">
          This is a Large-Participant Activity Proxy built from measurable price, volume, and F&O behaviour. It does
          not prove institutional buying and trader identity cannot be determined -- treat it as observable evidence,
          not fact.
        </p>
      </div>
    </section>
  );
}
