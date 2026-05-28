"""Web-knowledge sub-API error codes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Fetch error codes
# ---------------------------------------------------------------------------

#: The requested page type is not recognised.
WK_UNKNOWN_PAGE_TYPE = "WK001"

#: HTTP fetch failed (network error, timeout, or non-2xx status).
WK_FETCH_FAILED = "WK002"

#: The fetched page returned an empty body.
WK_EMPTY_RESPONSE = "WK003"

#: Exchange required for this page type but was not supplied.
WK_EXCHANGE_REQUIRED = "WK004"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

WK_ERRORS: dict[str, str] = {
    WK_UNKNOWN_PAGE_TYPE: "The requested page type is not recognised.",
    WK_FETCH_FAILED: "HTTP fetch failed (network error, timeout, or non-2xx status).",
    WK_EMPTY_RESPONSE: "The fetched page returned an empty body.",
    WK_EXCHANGE_REQUIRED: "Exchange required for this page type but was not supplied.",
}
