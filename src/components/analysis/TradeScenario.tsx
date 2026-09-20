import { ScenarioLevels, PositionSizing } from "../../types/api";

function fmt(n: number) {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

interface Props {
  scenarios: ScenarioLevels;
  positionSizing: PositionSizing;
}

export default function TradeScenarioSection({ scenarios, positionSizing }: Props) {
  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540]">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">
          MTF Trade Scenario
        </h2>
        <p className="text-[10px] text-[#475569] mt-1">
          Evidence-based scenario levels — not guaranteed targets
        </p>
      </div>

      {/* Visual price ladder */}
      <div className="px-5 py-5">
        <div className="relative">
          <div className="absolute left-4 top-4 bottom-4 w-px bg-[#1A2540]" />

          <div className="space-y-4">
            {scenarios.resistance_scenario_2 !== null && (
              <PriceLevel label={scenarios.resistance_scenario_2_label} price={fmt(scenarios.resistance_scenario_2)} color="#22C9B4" dotColor="#22C9B4" />
            )}
            <PriceLevel label={scenarios.resistance_scenario_1_label} price={fmt(scenarios.resistance_scenario_1)} color="#22C9B4" dotColor="#22C9B4" dim />
            <PriceLevel
              label={`Entry Zone  ·  Preferred: ${fmt(scenarios.preferred_entry)}`}
              price={`${fmt(scenarios.entry_zone_low)} – ${fmt(scenarios.entry_zone_high)}`}
              color="#CF8B2E"
              dotColor="#CF8B2E"
              highlight
            />
            <PriceLevel label="Invalidation (Stop Reference)" price={fmt(scenarios.invalidation)} color="#F05252" dotColor="#F05252" />
          </div>
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-2 border-t border-[#1A2540] divide-x divide-[#1A2540]">
        <div className="px-4 py-3 text-center">
          <div className="text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1">
            Reward : Risk (Scenario 1)
          </div>
          <div className="font-data font-semibold text-[#22C9B4] text-lg">
            {positionSizing.reward_to_risk_scenario_1 !== null ? `${positionSizing.reward_to_risk_scenario_1.toFixed(1)}:1` : "N/A"}
          </div>
        </div>
        <div className="px-4 py-3 text-center">
          <div className="text-[9px] font-heading uppercase tracking-widest text-[#475569] mb-1">
            Reward : Risk (Scenario 2)
          </div>
          <div className="font-data font-semibold text-[#CF8B2E] text-lg">
            {positionSizing.reward_to_risk_scenario_2 !== null ? `${positionSizing.reward_to_risk_scenario_2.toFixed(1)}:1` : "N/A"}
          </div>
        </div>
      </div>
    </section>
  );
}

function PriceLevel({
  label,
  price,
  color,
  dotColor,
  highlight = false,
  dim = false,
}: {
  label: string;
  price: string;
  color: string;
  dotColor: string;
  highlight?: boolean;
  dim?: boolean;
}) {
  return (
    <div className={`flex items-center gap-4 ${dim ? "opacity-70" : ""}`}>
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 border-2"
        style={{ borderColor: dotColor, background: highlight ? dotColor + "22" : "transparent" }}
      >
        <div className="w-2 h-2 rounded-full" style={{ background: dotColor }} />
      </div>
      <div className="flex-1">
        <div className="text-[10px] font-heading uppercase tracking-wider text-[#475569]">{label}</div>
        <div className="font-data font-semibold text-sm mt-0.5" style={{ color }}>
          {price}
        </div>
      </div>
    </div>
  );
}
