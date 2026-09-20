import { EvidenceItem } from "../../types/api";
import EvidenceList from "../ui/EvidenceList";

interface Props {
  summary: string;
  evidence: EvidenceItem[];
}

export default function WhySelectedSection({ summary, evidence }: Props) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-bold text-base text-white">Why This Stock Was Selected</h2>
      </div>

      {/* Summary (from the AI research engine, verbatim -- never rewritten client-side) */}
      <div className="px-5 py-5 border-b border-[#1A2540] bg-[#0B1018]">
        <p className="text-sm text-[#94A3B8] leading-relaxed whitespace-pre-line">{summary}</p>
      </div>

      {/* Evidence items */}
      <div className="px-5 py-4">
        <div className="text-[10px] font-heading uppercase tracking-widest text-[#475569] mb-4">
          Evidence
        </div>
        <EvidenceList items={evidence} emptyLabel="No evidence was recorded for this candidate." />
      </div>
    </section>
  );
}
