"""News sub-API error code registry package."""

from __future__ import annotations

from backend.resources.news.errors.codes import (
    NEWS_ERRORS,
    NEWS_FMP_AUTH_ERROR,
    NEWS_FMP_EMPTY,
    NEWS_NO_RESULTS,
    NEWS_PROVIDER_ERROR,
    NEWS_SEARCH_FAILED,
)

__all__ = [
    "NEWS_ERRORS",
    "NEWS_FMP_AUTH_ERROR",
    "NEWS_FMP_EMPTY",
    "NEWS_NO_RESULTS",
    "NEWS_PROVIDER_ERROR",
    "NEWS_SEARCH_FAILED",
]
