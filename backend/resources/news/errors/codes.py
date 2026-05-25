"""News sub-API error codes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# DDGS error codes
# ---------------------------------------------------------------------------

#: DDGS news or web-search returned no results.
NEWS_NO_RESULTS = "NEWS_NO_RESULTS"

#: DDGS news or web-search failed with an HTTP or network error.
NEWS_SEARCH_FAILED = "NEWS_SEARCH_FAILED"

# ---------------------------------------------------------------------------
# FMP error codes
# ---------------------------------------------------------------------------

#: FMP returned an empty news response.
NEWS_FMP_EMPTY = "NEWS_FMP_EMPTY"

#: FMP API key is missing or invalid (HTTP 401 / 403).
NEWS_FMP_AUTH_ERROR = "NEWS_FMP_AUTH_ERROR"

#: The FMP provider returned an unexpected error.
NEWS_PROVIDER_ERROR = "NEWS_PROVIDER_ERROR"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each news error code to a human-readable description.
NEWS_ERRORS: dict[str, str] = {
    NEWS_NO_RESULTS: "DDGS returned no results for the given query.",
    NEWS_SEARCH_FAILED: "DDGS search failed due to an HTTP or network error.",
    NEWS_FMP_EMPTY: "FMP returned an empty news response for the given symbol/topics/date range.",
    NEWS_FMP_AUTH_ERROR: "FMP API key is missing or invalid. Set FMP_API_KEY and restart.",
    NEWS_PROVIDER_ERROR: "FMP returned an unexpected error or is currently unavailable.",
}
