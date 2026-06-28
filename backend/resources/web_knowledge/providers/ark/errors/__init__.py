"""ARK web-search sub-API error code registry package."""

from __future__ import annotations

from backend.resources.web_knowledge.providers.ark.errors.codes import (
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
    "ARK_CONNECT_ERROR",
    "ARK_EMPTY_QUERY",
    "ARK_ERRORS",
    "ARK_HTTP_ERROR",
    "ARK_MALFORMED_RESPONSE",
    "ARK_MISSING_CREDENTIALS",
    "ARK_TIMEOUT",
    "ARK_WEB_SEARCH_UNSUPPORTED",
]
