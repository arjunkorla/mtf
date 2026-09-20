import { AiResearch } from "../../types/stock";
import { CheckCircle2, XCircle, AlertTriangle, Eye, ShieldQuestion, Calculator } from "lucide-react";
import DataUnavailable from "../ui/DataUnavailable";

interface Props {
  data: AiResearch | null;
}

const BLOCKS: { key: string; title: string; icon: React.ReactNode; color: string }[] = [
  { key: "STRONGEST EVIDENCE", title: "Strongest Evidence", icon: <CheckCircle2 size={12} />, color: "#22C9B4" },
  { key: "CONFLICTING EVIDENCE", title: "Conflicting Evidence", icon: <AlertTriangle size={12} />, color: "#F59E0B" },
  { key: "INSTITUTIONAL FOOTPRINT PROXY", title: "Institutional Footprint Proxy", icon: <ShieldQuestion size={12} />, color: "#94A3B8" },
  { key: "KEY RISKS", title: "Key Risks", icon: <XCircle size={12} />, color: "#F05252" },
  { key: "WHAT WOULD CONFIRM THE SETUP?", title: "What Would Confirm the Setup", icon: <Eye size={12} />, color: "#64748B" },
  { key: "WHAT WOULD INVALIDATE IT?", title: "What Would Invalidate It", icon: <XCircle size={12} />, color: "#F05252" },
  { key: "POSITION SIZING EXPLANATION", title: "Position Sizing Explanation", icon: <Calculator size={12} />, color: "#CF8B2E" },
];

function TextBlock({ icon, color, title, text }: { icon: React.ReactNode; color: string; title: string; text: string | undefined }) {
  return (
    <div className="border border-[#1A2540] rounded-lg p-4 bg-[#0B1018]">
      <div className="flex items-center gap-2 mb-3" style={{ color }}>
        {icon}
        <span className="text-[10px] font-heading font-semibold uppercase tracking-widest">{title}</span>
      </div>
      <p className="text-xs text-[#94A3B8] leading-relaxed whitespace-pre-line">{text || "Not provided."}</p>
    </div>
  );
}

export default function AIResearchSummarySection({ data }: Props) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">
          AI Research Summary
        </h2>
      </div>

      {data === null ? (
        <div className="px-5 py-8">
          <DataUnavailable label="AI research is not configured for this backend (AI_PROVIDER=none)" />
        </div>
      ) : (
        <>
          {data.flagged_unverified_numbers.length > 0 && (
            <div className="mx-5 mt-4 border border-[#4E3510] bg-[#2E1F06] rounded-lg p-3">
              <p className="text-[10px] text-[#F59E0B] leading-relaxed">
                The backend flagged numbers in this note that could not be matched to the source data:{" "}
                {data.flagged_unverified_numbers.join(", ")}. Treat those figures with caution.
              </p>
            </div>
          )}

          {/* Why selected */}
          <div className="px-5 py-5 border-b border-[#1A2540]">
            <div className="text-[10px] font-heading uppercase tracking-widest text-[#475569] mb-2">
              Why This Stock Appeared
            </div>
            <p className="text-sm text-[#94A3B8] leading-relaxed whitespace-pre-line">
              {data.sections["WHY WAS THIS STOCK SELECTED?"] || "Not provided."}
            </p>
          </div>

          <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
            {BLOCKS.map((b) => (
              <TextBlock key={b.key} icon={b.icon} color={b.color} title={b.title} text={data.sections[b.key]} />
            ))}
          </div>
        </>
      )}

      <div className="px-5 py-3 border-t border-[#1A2540] bg-[#0B1018]">
        <p className="text-[10px] text-[#374151] leading-relaxed">
          AI Research Summaries narrate data the backend already computed -- the AI does not calculate scores or
          invent figures. They do not constitute financial advice, a buy recommendation, or a guarantee of future
          performance. Always use your own judgment and risk management.
        </p>
      </div>
    </section>
  );
}
