"""News sub-API error codes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: Requested news article ID was not found.
NEWS_NOT_FOUND = "NEWS_NOT_FOUND"

#: Symbol provided is not recognised or supported.
NEWS_INVALID_SYMBOL = "NEWS_INVALID_SYMBOL"

#: The underlying news provider is unreachable or returned an error.
NEWS_PROVIDER_ERROR = "NEWS_PROVIDER_ERROR"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each news error code to a human-readable description.
NEWS_ERRORS: dict[str, str] = {
    NEWS_NOT_FOUND: (
        "The requested news article could not be found. "
        "The ID may be invalid or the article may have been removed."
    ),
    NEWS_INVALID_SYMBOL: (
        "The provided symbol is not recognised. "
        "Ensure the ticker is a valid equity symbol."
    ),
    NEWS_PROVIDER_ERROR: (
        "The news data provider returned an error or is currently unavailable. "
        "Try again later or check provider configuration."
    ),
}
