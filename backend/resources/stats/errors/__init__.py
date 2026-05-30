"""Stats sub-API error code registry package."""

from __future__ import annotations

from backend.resources.stats.errors.codes import (
    STATS_AKSHARE_EMPTY,
    STATS_ERRORS,
    STATS_FMP_AUTH_ERROR,
    STATS_FMP_EMPTY,
    STATS_INVALID_PERIOD,
    STATS_INVALID_SYMBOL,
    STATS_NOT_FOUND,
    STATS_PROVIDER_ERROR,
    STATS_YFINANCE_EMPTY,
)

__all__ = [
    "STATS_AKSHARE_EMPTY",
    "STATS_ERRORS",
    "STATS_FMP_AUTH_ERROR",
    "STATS_FMP_EMPTY",
    "STATS_INVALID_PERIOD",
    "STATS_INVALID_SYMBOL",
    "STATS_NOT_FOUND",
    "STATS_PROVIDER_ERROR",
    "STATS_YFINANCE_EMPTY",
]
