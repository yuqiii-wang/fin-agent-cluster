"""ARK web-search sub-API error codes.

The module follows the same ``{CODE}`` + ``{CODE}_ERRORS`` registry pattern used
by the sister ``web_knowledge`` and ``news`` sub-APIs so the rest of the
application can look up descriptions uniformly.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------

#: ``ARK_API_KEY`` (or ``ARK_WEB_SEARCH_API_KEY``) is not configured.
ARK_MISSING_CREDENTIALS = "ARK001"

#: The configured ARK base URL / model endpoint is not reachable.
ARK_CONNECT_ERROR = "ARK002"

# ---------------------------------------------------------------------------
# Runtime errors
# ---------------------------------------------------------------------------

#: The ARK endpoint returned a non-2xx HTTP status.
ARK_HTTP_ERROR = "ARK010"

#: The ARK endpoint refused the web-search tool (unsupported model / feature not enabled).
ARK_WEB_SEARCH_UNSUPPORTED = "ARK011"

#: The ARK endpoint timed out while producing the answer.
ARK_TIMEOUT = "ARK012"

#: The response payload could not be parsed into the expected schema.
ARK_MALFORMED_RESPONSE = "ARK013"

#: The query string was empty or contained only whitespace.
ARK_EMPTY_QUERY = "ARK014"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

ARK_ERRORS: dict[str, str] = {
    ARK_MISSING_CREDENTIALS: "ARK web-search credentials are not configured.",
    ARK_CONNECT_ERROR: "Cannot reach the ARK endpoint; check network or base URL.",
    ARK_HTTP_ERROR: "ARK endpoint returned a non-2xx HTTP status.",
    ARK_WEB_SEARCH_UNSUPPORTED: "The configured ARK model does not support the web_search tool.",
    ARK_TIMEOUT: "ARK web-search request timed out.",
    ARK_MALFORMED_RESPONSE: "ARK response payload did not match the expected schema.",
    ARK_EMPTY_QUERY: "The search query is empty or contains only whitespace.",
}
