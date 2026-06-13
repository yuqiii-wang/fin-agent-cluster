"""Stats sub-API error codes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: Requested stats record ID was not found.
STATS_NOT_FOUND = "STATS_NOT_FOUND"

#: Symbol provided is not recognised or supported.
STATS_INVALID_SYMBOL = "STATS_INVALID_SYMBOL"

#: Period parameter is not a supported aggregation interval.
STATS_INVALID_PERIOD = "STATS_INVALID_PERIOD"

#: The underlying market-data provider is unreachable or returned an error.
STATS_PROVIDER_ERROR = "STATS_PROVIDER_ERROR"

#: yfinance returned an empty DataFrame for the requested symbol / period.
STATS_YFINANCE_EMPTY = "STATS_YFINANCE_EMPTY"

#: FMP returned an empty or unrecognised response for the requested symbol / period.
STATS_FMP_EMPTY = "STATS_FMP_EMPTY"

#: FMP API key is missing or invalid (HTTP 401 / 403).
STATS_FMP_AUTH_ERROR = "STATS_FMP_AUTH_ERROR"

#: akshare returned an empty DataFrame for the requested symbol / period.
STATS_AKSHARE_EMPTY = "STATS_AKSHARE_EMPTY"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each stats error code to a human-readable description.
STATS_ERRORS: dict[str, str] = {
    STATS_NOT_FOUND: (
        "The requested statistics record could not be found. "
        "The ID may be invalid or no data exists for that symbol/period."
    ),
    STATS_INVALID_SYMBOL: (
        "The provided symbol is not recognised. "
        "Ensure the ticker is a valid equity symbol."
    ),
    STATS_INVALID_PERIOD: (
        "The requested period is not supported. "
        "Supported values are: '1d', '1w', '1mo', '3mo', '1y'."
    ),
    STATS_PROVIDER_ERROR: (
        "The market-data provider returned an error or is currently unavailable. "
        "Try again later or check provider configuration."
    ),
    STATS_YFINANCE_EMPTY: (
        "yfinance returned an empty DataFrame for the requested symbol and period. "
        "The symbol may be delisted or the period may be out of range."
    ),
    STATS_FMP_EMPTY: (
        "FMP returned an empty or unrecognised response for the requested symbol and period. "
        "The symbol may be unsupported by FMP or the date range may be out of bounds."
    ),
    STATS_FMP_AUTH_ERROR: (
        "FMP API key is missing or invalid. "
        "Set the FMP_API_KEY environment variable and restart the service."
    ),
    STATS_AKSHARE_EMPTY: (
        "akshare returned an empty DataFrame for the requested symbol and period. "
        "The A-share code may be invalid or no data is available for that date range."
    ),
}
