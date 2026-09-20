import { Ban } from "lucide-react";

/** Standard "this data was never fabricated" state. Used wherever the
 * backend marks a section `is_available: false` / a label as
 * INSUFFICIENT_DATA, or a value comes back null. Never replace these
 * call sites with a 0, an estimate, or an assumed sentiment. */
export default function DataUnavailable({ label = "Data unavailable" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-[#475569] font-heading italic">
      <Ban size={11} />
      {label}
    </span>
  );
}
