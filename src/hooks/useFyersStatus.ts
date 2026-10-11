import { useCallback, useEffect, useState } from "react";
import { getFyersStatus } from "../api/fyersApi";
import { FyersStatus } from "../api/fyersAuthState";

/** Tracks the backend's FYERS session status. Verifies once on mount (one
 * server-cached FYERS call), then re-checks locally whenever the tab regains
 * focus -- which is exactly when the user comes back from the FYERS login /
 * callback page. */
export function useFyersStatus(enabled: boolean) {
  const [status, setStatus] = useState<FyersStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  const recheck = useCallback(
    async (verify = false) => {
      if (!enabled) return;
      try {
        setStatus(await getFyersStatus(verify));
        setUnreachable(false);
      } catch {
        setUnreachable(true);
      }
    },
    [enabled],
  );

  useEffect(() => {
    if (!enabled) return;
    recheck(true);
    const onFocus = () => {
      if (document.visibilityState === "visible") recheck(false);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [enabled, recheck]);

  return { status, unreachable, recheck, setStatus };
}
