import { EvidenceItem } from "../../types/api";

/** Renders a list of backend EvidenceItem objects (label + detail + an
 * is_positive tri-state). Used everywhere the backend hands us "measurable
 * observation" evidence rather than a pre-classified strength -- we only
 * color the dot, we never re-derive a verdict the backend didn't give us. */
export default function EvidenceList({ items, emptyLabel = "No evidence available." }: { items: EvidenceItem[]; emptyLabel?: string }) {
  if (items.length === 0) {
    return <p className="text-xs text-[#475569]">{emptyLabel}</p>;
  }
  return (
    <ul className="space-y-2.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2.5">
          <span
            className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0"
            style={{
              background: item.is_positive === true ? "#22C9B4" : item.is_positive === false ? "#F05252" : "#475569",
            }}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-xs font-heading font-semibold text-[#E2E8F0]">{item.label}</span>
              {item.value !== null && (
                <span className="font-data text-[10px] text-[#64748B]">{String(item.value)}</span>
              )}
            </div>
            <p className="text-xs text-[#64748B] mt-0.5 leading-relaxed">{item.detail}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}
