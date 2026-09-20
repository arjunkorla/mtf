import { ScoreComponent } from "../../types/api";

interface Props {
  components: ScoreComponent[];
}

const LABELS: Record<string, string> = {
  technical_structure: "Technical Structure",
  volume_accumulation: "Volume / Accumulation",
  relative_strength: "Relative Strength",
  fno_positioning: "F&O Positioning",
  fundamentals: "Fundamentals",
  catalyst_news: "Catalyst / News",
  market_sector: "Market / Sector",
  data_quality: "Data Quality",
};

export default function ScoreBreakdownBar({ components }: Props) {
  return (
    <div className="space-y-2">
      {components.map((c) => {
        const pct = c.available && c.points_awarded !== null ? (c.points_awarded / c.weight) * 100 : 0;
        const color = !c.available ? "#374151" : pct >= 80 ? "#22C9B4" : pct >= 65 ? "#CF8B2E" : "#F05252";
        return (
          <div key={c.name} className="flex items-center gap-3" title={c.reason_unavailable ?? undefined}>
            <span className="text-xs text-[#64748B] w-40 shrink-0 font-heading">{LABELS[c.name] ?? c.name}</span>
            <div className="flex-1 h-1.5 bg-[#1A2540] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{ width: `${c.available ? pct : 0}%`, backgroundColor: color }}
              />
            </div>
            <span className="font-data text-xs w-16 text-right" style={{ color }}>
              {c.available && c.points_awarded !== null ? (
                <>
                  {c.points_awarded}
                  <span className="text-[#475569]">/{c.weight}</span>
                </>
              ) : (
                "N/A"
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
