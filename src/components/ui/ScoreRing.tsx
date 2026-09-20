interface ScoreRingProps {
  score: number;
  max?: number;
  size?: "sm" | "md" | "lg";
}

export default function ScoreRing({ score, max = 100, size = "md" }: ScoreRingProps) {
  const pct = score / max;
  const dims = { sm: 56, md: 72, lg: 96 };
  const strokes = { sm: 4, md: 5, lg: 6 };
  const d = dims[size];
  const s = strokes[size];
  const r = (d - s * 2) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - pct);

  const color = pct >= 0.8 ? "#22C9B4" : pct >= 0.65 ? "#CF8B2E" : "#F05252";
  const textSizes = { sm: "text-sm", md: "text-lg", lg: "text-2xl" };

  return (
    <div className="relative flex items-center justify-center" style={{ width: d, height: d }}>
      <svg width={d} height={d} className="rotate-[-90deg]">
        <circle cx={d / 2} cy={d / 2} r={r} fill="none" stroke="#1A2540" strokeWidth={s} />
        <circle
          cx={d / 2}
          cy={d / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={s}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span
          className={`font-data font-semibold ${textSizes[size]}`}
          style={{ color }}
        >
          {score}
        </span>
        {size !== "sm" && (
          <span className="text-[9px] text-[#64748B] font-heading tracking-widest uppercase">
            /{max}
          </span>
        )}
      </div>
    </div>
  );
}
