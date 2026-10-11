import { FYERS_LOGIN_URL } from "../../api/fyersApi";
import { FyersStatus, fyersIndicator } from "../../api/fyersAuthState";

/** Compact header indicator: "FYERS ● Connected" / "FYERS ○ Login Required [Connect]". */
export default function FyersStatusBadge({ status, unreachable }: { status: FyersStatus | null; unreachable: boolean }) {
  const ind = fyersIndicator(status, unreachable);
  return (
    <div className="flex items-center gap-1.5" title={status?.message ?? undefined}>
      <span className="text-[10px] font-data text-[#475569]">FYERS</span>
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={ind.connected ? { background: ind.color } : { border: `1px solid ${ind.color}` }}
      />
      <span className="text-[10px] font-data hidden sm:block" style={{ color: ind.color }}>
        {ind.label}
      </span>
      {ind.needsLogin && (
        <a
          href={FYERS_LOGIN_URL}
          className="ml-1 text-[10px] font-heading font-semibold px-2 py-0.5 rounded bg-[#CF8B2E] text-[#080B10] hover:opacity-90"
        >
          Connect FYERS
        </a>
      )}
    </div>
  );
}
