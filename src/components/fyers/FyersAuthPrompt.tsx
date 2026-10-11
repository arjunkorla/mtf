import { useState, type FormEvent } from "react";
import { KeyRound, LogIn } from "lucide-react";
import { FYERS_LOGIN_URL, refreshFyersWithPin } from "../../api/fyersApi";
import { FyersStatus } from "../../api/fyersAuthState";

/** Shown instead of a raw "HTTP 401" when the FYERS session is gone.
 * "Connect FYERS" runs the full login in this tab (the callback page links
 * back here). If the backend holds a refresh token, the user can instead
 * type their PIN once -- it is posted to the backend and never stored. */
export default function FyersAuthPrompt({
  status,
  onReconnected,
}: {
  status: FyersStatus | null;
  onReconnected: (s: FyersStatus) => void;
}) {
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [pinError, setPinError] = useState<string | null>(null);
  const canUsePin = status?.status === "REFRESH_REQUIRED" && status.refresh_available;

  const submitPin = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setPinError(null);
    try {
      onReconnected(await refreshFyersWithPin(pin));
    } catch (err) {
      setPinError(err instanceof Error ? err.message : "PIN refresh failed");
    } finally {
      setPin("");
      setBusy(false);
    }
  };

  return (
    <div className="border border-[#4E3A1B] bg-[#2A1F0E] rounded-lg p-5">
      <p className="text-sm font-heading font-semibold text-[#F59E0B]">FYERS session expired.</p>
      <p className="text-xs text-[#94A3B8] mt-1">
        Reconnect FYERS to continue. No market data was fabricated -- the scan stopped instead.
      </p>
      <div className="flex flex-wrap items-center gap-3 mt-4">
        <a
          href={FYERS_LOGIN_URL}
          className="inline-flex items-center gap-2 px-4 py-2 rounded bg-[#CF8B2E] text-[#080B10] text-sm font-heading font-semibold hover:opacity-90"
        >
          <LogIn size={14} /> Connect FYERS
        </a>
        {canUsePin && (
          <form onSubmit={submitPin} className="flex items-center gap-2">
            <span className="text-xs text-[#64748B]">or reconnect with PIN</span>
            <input
              type="password"
              inputMode="numeric"
              autoComplete="off"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
              className="w-20 bg-[#0B1018] border border-[#1A2540] rounded px-2 py-1.5 text-sm font-data text-white focus:outline-none focus:border-[#CF8B2E]"
              aria-label="FYERS PIN"
            />
            <button
              type="submit"
              disabled={busy || pin.length < 4}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded border border-[#CF8B2E] text-[#CF8B2E] text-xs font-heading font-semibold disabled:opacity-40"
            >
              <KeyRound size={12} /> {busy ? "Reconnecting…" : "Reconnect"}
            </button>
          </form>
        )}
      </div>
      {pinError && <p className="text-xs text-[#F05252] mt-2">{pinError}</p>}
    </div>
  );
}
