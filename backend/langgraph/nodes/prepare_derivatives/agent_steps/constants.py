"""constants.py — Step-name constants for the prepare_derivatives agent steps."""

from __future__ import annotations

STEP_NAVIGATE_WEB: str = "navigate_web"
STEP_GET_STATS: str = "get_stats"
STEP_CALCULATE_OPTIONS: str = "calculate_options"

# Canonical execution order.
STEP_ORDER: list[str] = [
    STEP_NAVIGATE_WEB,
    STEP_GET_STATS,
    STEP_CALCULATE_OPTIONS,
]

__all__ = [
    "STEP_NAVIGATE_WEB",
    "STEP_GET_STATS",
    "STEP_CALCULATE_OPTIONS",
    "STEP_ORDER",
]

