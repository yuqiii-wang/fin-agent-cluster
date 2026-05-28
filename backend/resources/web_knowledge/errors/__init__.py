"""Web-knowledge sub-API error code registry package."""

from __future__ import annotations

from backend.resources.web_knowledge.errors.codes import (
    WK_EMPTY_RESPONSE,
    WK_ERRORS,
    WK_EXCHANGE_REQUIRED,
    WK_FETCH_FAILED,
    WK_UNKNOWN_PAGE_TYPE,
)

__all__ = [
    "WK_ERRORS",
    "WK_EMPTY_RESPONSE",
    "WK_EXCHANGE_REQUIRED",
    "WK_FETCH_FAILED",
    "WK_UNKNOWN_PAGE_TYPE",
]
