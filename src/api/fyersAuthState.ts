/**
 * Pure FYERS auth-state helpers (no React, no fetch, no import.meta) so they
 * can be unit-tested with `node --test`. Tokens never reach the frontend --
 * everything here works from the backend's safe /api/fyers/status payload
 * and the FYERS_AUTH_REQUIRED error code.
 */

export type FyersStatusCode = "CONNECTED" | "REFRESH_REQUIRED" | "LOGIN_REQUIRED" | "MOCK" | "ERROR";

/** Mirrors GET /api/fyers/status (backend/app/integrations/fyers/session.py). */
export interface FyersStatus {
  mode: "live" | "mock";
  status: FyersStatusCode;
  authenticated: boolean;
  refresh_available: boolean;
  refresh_requires_pin: boolean;
  verified: boolean;
  last_verified_at: string | null;
  verification_error: string | null;
  access_expires_at: string | null;
  refresh_expires_at: string | null;
  token_source: string;
  login_url: string;
  message: string;
}

export const FYERS_AUTH_REQUIRED = "FYERS_AUTH_REQUIRED";

/** True for the backend's structured "reconnect FYERS" error (HTTP 401 +
 * code FYERS_AUTH_REQUIRED), as opposed to any other scan failure. */
export function isFyersAuthRequired(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { code?: unknown }).code === FYERS_AUTH_REQUIRED;
}

export function fyersLoginUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl.replace(/\/+$/, "")}/fyers/login`;
}

export interface FyersIndicator {
  label: string;
  color: string;
  connected: boolean;
  /** Show the "Connect FYERS" action. */
  needsLogin: boolean;
  /** A stored refresh token allows reconnecting with just the PIN. */
  canRefreshWithPin: boolean;
}

export function fyersIndicator(status: FyersStatus | null, unreachable = false): FyersIndicator {
  const base = { connected: false, needsLogin: false, canRefreshWithPin: false };
  if (unreachable) return { ...base, label: "Unknown", color: "#475569" };
  if (!status) return { ...base, label: "Checking", color: "#F59E0B" };
  switch (status.status) {
    case "CONNECTED":
      return { ...base, label: "Connected", color: "#22C9B4", connected: true };
    case "MOCK":
      return { ...base, label: "Mock", color: "#CF8B2E", connected: true };
    case "REFRESH_REQUIRED":
      return { ...base, label: "Session Expired", color: "#F59E0B", needsLogin: true, canRefreshWithPin: true };
    case "LOGIN_REQUIRED":
      return { ...base, label: "Login Required", color: "#F05252", needsLogin: true };
    default:
      return { ...base, label: "Not Configured", color: "#F05252" };
  }
}
