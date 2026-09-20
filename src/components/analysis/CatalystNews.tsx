import { NewsData, NewsSentiment } from "../../types/stock";

const SENTIMENT_STYLES: Record<NewsSentiment, { color: string; bg: string; label: string }> = {
  POSITIVE: { color: "#22C9B4", bg: "#0E2E2A", label: "Positive" },
  NEUTRAL: { color: "#94A3B8", bg: "#1A2135", label: "Neutral" },
  NEGATIVE: { color: "#F05252", bg: "#2E1212", label: "Negative" },
  UNKNOWN: { color: "#64748B", bg: "#141D2E", label: "Unknown" },
};

export default function CatalystNewsSection({ data }: { data: NewsData }) {
  if (data.items.length === 0) {
    return (
      <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] p-5">
        <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider mb-3">
          Catalysts / News
        </h2>
        <p className="text-xs text-[#475569]">No news or catalyst data is available for this stock.</p>
      </section>
    );
  }

  const overall = SENTIMENT_STYLES[data.overall_sentiment];

  return (
    <section className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1A2540] flex items-center justify-between">
        <div>
          <h2 className="font-heading font-semibold text-sm text-white uppercase tracking-wider">Catalysts / News</h2>
          <p className="text-[10px] text-[#475569] mt-1">Recent events that may be relevant to this setup</p>
        </div>
        <span
          className="text-[9px] font-heading font-semibold uppercase tracking-wider px-2 py-0.5 rounded shrink-0"
          style={{ color: overall.color, background: overall.bg }}
        >
          Overall {overall.label}
        </span>
      </div>
      <div className="divide-y divide-[#1A2540]">
        {data.items.map((item, i) => {
          const style = SENTIMENT_STYLES[item.sentiment];
          return (
            <div key={i} className="px-5 py-3.5 flex items-start gap-3">
              <div className="flex flex-col items-end gap-1 shrink-0 mt-0.5">
                <span className="font-data text-[10px] text-[#475569]">
                  {new Date(item.published_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
                </span>
                <span
                  className="text-[9px] font-heading font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
                  style={{ color: style.color, background: style.bg }}
                >
                  {style.label}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                {item.source_url ? (
                  <a href={item.source_url} target="_blank" rel="noreferrer" className="text-sm text-[#E2E8F0] leading-snug hover:text-[#CF8B2E] transition-colors">
                    {item.headline}
                  </a>
                ) : (
                  <p className="text-sm text-[#E2E8F0] leading-snug">{item.headline}</p>
                )}
                <p className="text-[10px] text-[#475569] font-heading uppercase tracking-wider mt-1">
                  {item.category ?? "Uncategorized"} · {item.source}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
