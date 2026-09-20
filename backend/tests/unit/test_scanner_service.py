"""Regression tests for scanner_service._classify_error (Phase 1 fix): every
non-filter analysis failure used to collapse into a single "calculation_error"
bucket, which hid the real cause (e.g. FYERS rejecting a stale/invalid symbol
with HTTP 422) behind what looked like a bug in our own code."""

from app.core.exceptions import FyersApiError, FyersAuthError, FyersRateLimitError, InsufficientDataError
from app.services.scanner_service import _classify_error


def test_invalid_symbol_maps_to_invalid_symbol():
    exc = FyersApiError("FYERS API error on /history: HTTP 422", status_code=422)
    assert _classify_error(exc) == "invalid_symbol"


def test_not_found_symbol_maps_to_invalid_symbol():
    exc = FyersApiError("FYERS API error on /history: HTTP 404", status_code=404)
    assert _classify_error(exc) == "invalid_symbol"


def test_upstream_server_error_maps_to_api_unavailable():
    exc = FyersApiError("FYERS API error on /history: HTTP 503", status_code=503)
    assert _classify_error(exc) == "api_unavailable"


def test_generic_fyers_error_without_status_maps_to_api_error():
    exc = FyersApiError("FYERS API returned error on /quotes: unknown")
    assert _classify_error(exc) == "api_error"


def test_rate_limit_error_maps_to_api_rate_limited():
    exc = FyersRateLimitError("Rate limited by FYERS on /history", status_code=429)
    assert _classify_error(exc) == "api_rate_limited"


def test_auth_error_maps_to_api_auth_error():
    exc = FyersAuthError("FYERS credentials missing")
    assert _classify_error(exc) == "api_auth_error"


def test_insufficient_data_error_maps_to_insufficient_data():
    exc = InsufficientDataError("not enough candles to compute indicators")
    assert _classify_error(exc) == "insufficient_data"


def test_unrecognized_exception_maps_to_calculation_error():
    """A genuine bug in our own code -- not an external data/API problem --
    must still land in calculation_error, distinct from every case above."""
    exc = ZeroDivisionError("simulated bug")
    assert _classify_error(exc) == "calculation_error"
