"""News sub-API error code registry package."""

from __future__ import annotations

from backend.resources.news.errors.codes import (
    NEWS_ERRORS,
    NEWS_INVALID_SYMBOL,
    NEWS_NOT_FOUND,
    NEWS_PROVIDER_ERROR,
)

__all__ = [
    "NEWS_ERRORS",
    "NEWS_INVALID_SYMBOL",
    "NEWS_NOT_FOUND",
    "NEWS_PROVIDER_ERROR",
]
