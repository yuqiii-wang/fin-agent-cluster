"""Error codes for the common_tasks module."""

from __future__ import annotations

STATS_TASK_NO_DATA = "STATS_TASK_NO_DATA"
STATS_TASK_PROVIDER_ERROR = "STATS_TASK_PROVIDER_ERROR"
STATS_TASK_CALC_ERROR = "STATS_TASK_CALC_ERROR"
STATS_TASK_CORR_INSUFFICIENT_DATA = "STATS_TASK_CORR_INSUFFICIENT_DATA"
STATS_TASK_UNSUPPORTED_PERIOD = "STATS_TASK_UNSUPPORTED_PERIOD"
STATS_TASK_PERIOD_FALLBACK = "STATS_TASK_PERIOD_FALLBACK"
STATS_TASK_PROVIDER_FALLBACK = "STATS_TASK_PROVIDER_FALLBACK"

STATS_TASK_ERRORS: dict[str, str] = {
    STATS_TASK_NO_DATA: "No stats data returned from provider for the given symbol/period.",
    STATS_TASK_PROVIDER_ERROR: "External stats provider raised an error.",
    STATS_TASK_CALC_ERROR: "Failed to compute technical indicators from OHLCV series.",
    STATS_TASK_CORR_INSUFFICIENT_DATA: "Insufficient bar data to compute Pearson correlation.",
    STATS_TASK_UNSUPPORTED_PERIOD: "Requested period is not supported for indicator calculation.",
    STATS_TASK_PERIOD_FALLBACK: "Requested period unavailable; fell back to a shorter period.",
    STATS_TASK_PROVIDER_FALLBACK: "Primary provider returned no data; fell back to an alternative provider.",
}

__all__ = [
    "STATS_TASK_NO_DATA",
    "STATS_TASK_PROVIDER_ERROR",
    "STATS_TASK_CALC_ERROR",
    "STATS_TASK_CORR_INSUFFICIENT_DATA",
    "STATS_TASK_UNSUPPORTED_PERIOD",
    "STATS_TASK_PERIOD_FALLBACK",
    "STATS_TASK_PROVIDER_FALLBACK",
    "STATS_TASK_ERRORS",
]
