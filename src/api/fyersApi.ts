import { BASE_URL, client } from "./client";
import { FyersStatus, fyersLoginUrl } from "./fyersAuthState";

/** Full-page navigation target: backend 302s to FYERS, FYERS redirects to
 * the backend callback, which stores the session server-side and links back
 * here. No token ever passes through the frontend. */
export const FYERS_LOGIN_URL = fyersLoginUrl(BASE_URL);

/** GET /api/fyers/status. `verify` makes the backend confirm the session
 * with one (server-cached) FYERS call instead of a purely local check. */
export function getFyersStatus(verify = false): Promise<FyersStatus> {
  return client.get<FyersStatus>(`/fyers/status${verify ? "?verify=true" : ""}`);
}

/** POST /api/fyers/refresh -- one refresh attempt with the PIN the user just
 * typed. The PIN is sent once and never stored in the browser. */
export function refreshFyersWithPin(pin: string): Promise<FyersStatus> {
  return client.post<FyersStatus>("/fyers/refresh", { pin });
}
