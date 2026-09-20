import { RealtimeConfirmationResponse } from "../types/confirmation";
import { client } from "./client";

/** GET /api/scanner/{symbol}/realtime-confirmation -- on-demand only, never
 * called automatically for every scanner candidate (see
 * RealtimeConfirmationBadge.tsx: fetched lazily on expand, not on scan). */
export function getRealtimeConfirmation(symbol: string): Promise<RealtimeConfirmationResponse> {
  return client.get<RealtimeConfirmationResponse>(`/scanner/${encodeURIComponent(symbol)}/realtime-confirmation`);
}
