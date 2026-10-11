"""Application-level exceptions."""


class MtfError(Exception):
    """Base exception for all domain errors in this service."""


class FyersApiError(MtfError):
    """Raised when the FYERS API returns an error or an unexpected shape.

    `status_code` carries the underlying HTTP status when known, so callers
    (e.g. scanner_service's per-symbol error classification) can distinguish
    an invalid/delisted symbol (404/422) from a transient upstream outage
    (5xx) instead of treating every FYERS failure identically.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class FyersAuthError(FyersApiError):
    """Raised when FYERS authentication/token refresh fails."""


class FyersAuthRequiredError(FyersAuthError):
    """Raised when FYERS rejected the session (HTTP 401) and it could not be
    recovered automatically -- the user must reconnect (PIN refresh or full
    login). Surfaced to the frontend as HTTP 401 with code FYERS_AUTH_REQUIRED
    rather than a generic 502, and never swallowed into a partial scan."""

    code = "FYERS_AUTH_REQUIRED"


class FyersRateLimitError(FyersApiError):
    """Raised on a 429 from FYERS -- distinct from other 4xx/5xx so it can be
    retried with backoff instead of failing the candidate immediately."""


class FyersLocalCapacityExceeded(FyersRateLimitError):
    """Raised by our OWN process-wide limiter (request_control.py) when a
    request could not be admitted within its priority tier's max wait, or
    the daily safety ceiling is reached. The request was never sent to
    FYERS. Subclasses FyersRateLimitError so existing callers classify it as
    rate-limited, but FyersClient never retries it (retrying would only
    queue behind the same exhausted budget)."""


class InsufficientDataError(MtfError):
    """Raised when a calculation cannot proceed because required data is missing.

    TECHNICAL DEBT (Phase 6 investigation, 2026-09-20): defined and handled
    (scanner_service._classify_error maps it to the "insufficient_data"
    rejection reason) but nothing in the codebase actually raises it today
    -- every current insufficient-data case is instead caught earlier via
    CandidateRejected (build_candidate's hard filters) or by the engines
    returning None/INSUFFICIENT_DATA rather than raising. Left in place
    rather than removed: it costs nothing to keep, the classification
    branch that depends on it is otherwise-untouched forward-compatible
    dead code, and removing it would mean also removing that branch for no
    real benefit. Revisit only if a future engine genuinely needs to raise
    mid-calculation instead of returning a sentinel.
    """


class CandidateRejectedError(MtfError):
    """Raised internally by the filtering stage; carries the rejection reason."""

    def __init__(self, symbol: str, reason: str):
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"{symbol} rejected: {reason}")


class AiProviderError(MtfError):
    """Raised when the AI research engine fails to get a usable response."""
