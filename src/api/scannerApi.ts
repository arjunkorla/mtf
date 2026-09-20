import { ScannerRunRequest, ScannerRunResponse, ScannerResultsResponse } from "../types/scanner";
import { MOCK_SCANNER_RESPONSE } from "../mock/scannerData";
import { client } from "./client";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

/** POST /api/scanner/run -- the backend computes and ranks every candidate;
 * this never recalculates scores or risk figures client-side. */
export async function runScan(request: ScannerRunRequest): Promise<ScannerRunResponse> {
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 1500));
    return { ...MOCK_SCANNER_RESPONSE, generated_at: new Date().toISOString() };
  }
  return client.post<ScannerRunResponse>("/scanner/run", request);
}

/** GET /api/scanner/results -- latest completed run, or a specific run_id. */
export async function getScannerResults(runId?: number): Promise<ScannerResultsResponse> {
  if (USE_MOCK) {
    return { run_id: MOCK_SCANNER_RESPONSE.run_id, status: MOCK_SCANNER_RESPONSE.status, generated_at: MOCK_SCANNER_RESPONSE.generated_at, candidates: MOCK_SCANNER_RESPONSE.candidates };
  }
  const query = runId != null ? `?run_id=${runId}` : "";
  return client.get<ScannerResultsResponse>(`/scanner/results${query}`);
}
