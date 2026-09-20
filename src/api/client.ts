import { ApiError, HealthResponse } from "../types/api";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";
const DEFAULT_TIMEOUT_MS = 20000;

/** The exact message required whenever a request never reaches the backend
 * at all (connection refused, DNS failure) -- never shown for an HTTP error
 * response, which means the backend IS running. */
const BACKEND_UNAVAILABLE_MESSAGE = "Backend unavailable. Start the FastAPI server and try again.";

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      // FastAPI/Pydantic validation errors: [{loc, msg, type}, ...]
      return body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ") || `Request failed (${res.status})`;
    }
  } catch {
    /* response wasn't JSON */
  }
  return `Request failed (${res.status})`;
}

async function request<T>(path: string, options?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      ...options,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(`Request timed out after ${timeoutMs / 1000}s. The backend may be slow or unresponsive.`, {
        isNetworkError: true,
      });
    }
    throw new ApiError(BACKEND_UNAVAILABLE_MESSAGE, { isNetworkError: true });
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    const detail = await parseErrorDetail(res);
    throw new ApiError(detail, { status: res.status });
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const client = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};

/** GET /api/health -- used to detect "backend not running" before/independent
 * of any scan, e.g. for a connectivity indicator in the header. */
export function checkHealth(): Promise<HealthResponse> {
  return client.get<HealthResponse>("/health");
}

export { BACKEND_UNAVAILABLE_MESSAGE };
