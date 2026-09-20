import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronDown,
  ChevronUp,
  TrendingUp,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
} from "lucide-react";
import { CandidateResponse } from "../../types/stock";
import ScoreRing from "../ui/ScoreRing";
import { SignalQualityBadge, StrengthBadge } from "../ui/Badge";
import RealtimeConfirmationBadge from "./RealtimeConfirmationBadge";

function fmt(n: number) {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

interface Props {
  candidate: CandidateResponse;
  rank: number;
  holdingPeriod: string;
}

export default function StockCard({ candidate, rank, holdingPeriod }: Props) {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();

  const rewardToRisk1 = candidate.position_sizing.reward_to_risk_scenario_1;

  return (
    <div className="border border-[#1A2540] rounded-lg bg-[#0F1520] hover:border-[#25344E] transition-colors duration-200 overflow-hidden">
      {/* Header row */}
      <div className="flex items-start gap-4 p-5">
        {/* Rank + Score */}
        <div className="flex flex-col items-center gap-2 shrink-0">
          <span className="font-data text-xs text-[#475569]">#{rank}</span>
          <ScoreRing score={candidate.score} size="md" />
          <span className="text-[9px] font-heading text-[#475569] uppercase tracking-widest text-center leading-tight">
            MTF Setup
            <br />Score
          </span>
        </div>

        {/* Stock info */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-heading font-bold text-xl text-white tracking-tight">
                  {candidate.symbol}
                </h3>
                <SignalQualityBadge quality={candidate.signal_quality} />
                <StrengthBadge strength={candidate.institutional_footprint.institutional_footprint_level} />
                <span className="text-[10px] font-data text-[#475569]">
                  Data {candidate.data_quality.data_quality_score.toFixed(0)}%
                </span>
              </div>
              <p className="text-sm text-[#64748B] mt-0.5">{candidate.company_name}</p>
            </div>
            <div className="text-right">
              <div className="font-data font-semibold text-xl text-white">{fmt(candidate.price)}</div>
              <div className="text-[10px] font-heading text-[#64748B] uppercase tracking-wider mt-0.5">
                Current Price
              </div>
            </div>
          </div>

          {/* Key metrics grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <Metric label="Entry Zone" value={`${fmt(candidate.entry_zone_low)} – ${fmt(candidate.entry_zone_high)}`} />
            <Metric label="Preferred Entry" value={fmt(candidate.scenarios.preferred_entry)} />
            <Metric label="Invalidation" value={fmt(candidate.invalidation)} valueClass="text-[#F05252]" />
            <Metric label="Scenario 1" value={fmt(candidate.scenarios.resistance_scenario_1)} valueClass="text-[#22C9B4]" />
            <Metric
              label="Scenario 2"
              value={candidate.scenarios.resistance_scenario_2 !== null ? fmt(candidate.scenarios.resistance_scenario_2) : "N/A"}
              valueClass="text-[#22C9B4]"
            />
          </div>

          {/* Capital row */}
          <div className="mt-3 pt-3 border-t border-[#1A2540] flex flex-wrap gap-4 text-xs">
            <span className="text-[#64748B]">
              Suggested Capital{" "}
              <span className="font-data text-[#E2E8F0]">{fmt(candidate.position_sizing.capital_required)}</span>
            </span>
            <span className="text-[#64748B]">
              Estimated Risk{" "}
              <span className="font-data text-[#F05252]">{fmt(candidate.position_sizing.max_rupee_risk)}</span>
            </span>
            <span className="text-[#64748B]">
              Qty <span className="font-data text-[#E2E8F0]">{candidate.position_sizing.quantity} shares</span>
            </span>
            {rewardToRisk1 !== null && (
              <span className="text-[#64748B]">
                R:R (S1) <span className="font-data text-[#22C9B4]">{rewardToRisk1.toFixed(1)}:1</span>
              </span>
            )}
            <span className="text-[#64748B]">
              Horizon <span className="font-heading text-[#94A3B8]">{holdingPeriod}</span>
            </span>
          </div>
        </div>
      </div>

      {/* Expandable evidence + risks */}
      <div className="border-t border-[#1A2540]">
        <button
          className="w-full flex items-center justify-between px-5 py-3 text-xs text-[#64748B] hover:text-[#94A3B8] hover:bg-[#111928] transition-colors"
          onClick={() => setExpanded((x) => !x)}
        >
          <span className="font-heading uppercase tracking-wider">Evidence & Risks</span>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {expanded && (
          <>
            {/* Fetched only now, on expand -- never during the scan itself
                (see RealtimeConfirmationBadge.tsx); does not affect ranking/selection. */}
            <div className="px-5 pt-3">
              <RealtimeConfirmationBadge symbol={candidate.symbol} />
            </div>
            <div className="px-5 pb-5 grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <div className="flex items-center gap-1.5 mb-3">
                <TrendingUp size={12} className="text-[#22C9B4]" />
                <span className="text-[10px] font-heading uppercase tracking-widest text-[#22C9B4]">
                  Key Evidence
                </span>
              </div>
              {candidate.evidence.length === 0 ? (
                <p className="text-xs text-[#475569]">No evidence available.</p>
              ) : (
                <ul className="space-y-1.5">
                  {candidate.evidence.map((e, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-[#94A3B8]">
                      <CheckCircle2 size={11} className="text-[#22C9B4] mt-0.5 shrink-0" />
                      <span>
                        <span className="font-semibold text-[#E2E8F0]">{e.label}:</span> {e.detail}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-3">
                <AlertTriangle size={12} className="text-[#F59E0B]" />
                <span className="text-[10px] font-heading uppercase tracking-widest text-[#F59E0B]">
                  Key Risks
                </span>
              </div>
              {candidate.risks.length === 0 ? (
                <p className="text-xs text-[#475569]">No risks flagged.</p>
              ) : (
                <ul className="space-y-1.5">
                  {candidate.risks.map((r, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-[#94A3B8]">
                      <AlertTriangle size={11} className="text-[#F59E0B] mt-0.5 shrink-0" />
                      {r}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            </div>
          </>
        )}
      </div>

      {/* CTA */}
      <div className="border-t border-[#1A2540] bg-[#0B1018]">
        <button
          onClick={() => navigate(`/analysis/${encodeURIComponent(candidate.symbol)}`)}
          className="w-full flex items-center justify-center gap-2 py-3 text-xs font-heading font-semibold uppercase tracking-widest text-[#CF8B2E] hover:text-white hover:bg-[#CF8B2E] transition-all duration-200"
        >
          View Detailed Analysis
          <ArrowRight size={13} />
        </button>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  valueClass = "text-[#E2E8F0]",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="bg-[#0B1018] rounded p-2.5 border border-[#1A2540]">
      <div className="text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1">{label}</div>
      <div className={`font-data text-sm font-medium ${valueClass} leading-tight`}>{value}</div>
    </div>
  );
}
