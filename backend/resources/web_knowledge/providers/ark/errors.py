"""Stable error codes surfaced by :class:`ArkWebSearchClient`.

Using short, prefix codes follow a stable naming scheme so callers can react
programmatically.  The raw HTTP and library errors are re-raised as
``ValueError`` with ``[CODE] prefixes``.  This file exposes the string
constants so callers can easily ``.startswith`` against them.
"""
from __future__ import annotations

ARK_MISSING_CREDENTIALS = "ARK_MISSING_CREDENTIALS"
ARK_EMPTY_QUERY = "ARK_EMPTY_QUERY"
ARK_HTTP_ERROR = "ARK_HTTP_ERROR"
ARK_TIMEOUT = "ARK_TIMEOUT"
ARK_CONNECT_ERROR = "ARK_CONNECT_ERROR"
ARK_MALFORMED_RESPONSE = "ARK_MALFORMED_RESPONSE"
ARK_WEB_SEARCH_UNSUPPORTED = "ARK_WEB_SEARCH_UNSUPPORTED"

__all__ = [
    "ARK_MISSING_CREDENTIALS",
    "ARK_EMPTY_QUERY",
    "ARK_HTTP_ERROR",
    "ARK_TIMEOUT",
    "ARK_CONNECT_ERROR",
    "ARK_MISSING_CREDENTIALS",
    "ARK_MALFORMED_RESPONSE",
    "ARK_WEB_SEARCH_UNSUPPORTED",
]
