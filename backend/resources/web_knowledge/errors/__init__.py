"""Web-knowledge sub-API error code registry package.

Re-exports both the plain HTML-fetch error codes (``WK_*``) and the
ARK / Doubao ``web_search`` tool error codes (``ARK_*``) so callers can
look up any failure code relevant to the web-knowledge client in one
place.
"""

from __future__ import annotations

from backend.resources.web_knowledge.errors.codes import (
    WK_EMPTY_RESPONSE,
    WK_ERRORS,
    WK_EXCHANGE_REQUIRED,
    WK_FETCH_FAILED,
    WK_UNKNOWN_PAGE_TYPE,
)
from backend.resources.web_knowledge.providers.ark.errors import (
    ARK_CONNECT_ERROR,
    ARK_EMPTY_QUERY,
    ARK_ERRORS,
    ARK_HTTP_ERROR,
    ARK_MALFORMED_RESPONSE,
    ARK_MISSING_CREDENTIALS,
    ARK_TIMEOUT,
    ARK_WEB_SEARCH_UNSUPPORTED,
)

__all__ = [
    # HTML fetch / URL builder errors
    "WK_EMPTY_RESPONSE",
    "WK_ERRORS",
    "WK_EXCHANGE_REQUIRED",
    "WK_FETCH_FAILED",
    "WK_UNKNOWN_PAGE_TYPE",
    # ARK web-search tool errors
    "ARK_CONNECT_ERROR",
    "ARK_EMPTY_QUERY",
    "ARK_ERRORS",
    "ARK_HTTP_ERROR",
    "ARK_MALFORMED_RESPONSE",
    "ARK_MISSING_CREDENTIALS",
    "ARK_TIMEOUT",
    "ARK_WEB_SEARCH_UNSUPPORTED",
]
