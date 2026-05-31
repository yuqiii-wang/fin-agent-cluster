"""constants.py — Step-name constants for the prepare_derivatives agent steps."""

from __future__ import annotations

STEP_LOAD_MARKDOWN: str = "load_markdown"
STEP_STUDY_WEB: str = "study_web"
STEP_GET_STATS: str = "get_stats"
STEP_CALCULATE_OPTIONS: str = "calculate_options"

# Canonical execution order.
STEP_ORDER: list[str] = [
    STEP_LOAD_MARKDOWN,
    STEP_STUDY_WEB,
    STEP_GET_STATS,
    STEP_CALCULATE_OPTIONS,
]

__all__ = [
    "STEP_LOAD_MARKDOWN",
    "STEP_STUDY_WEB",
    "STEP_GET_STATS",
    "STEP_CALCULATE_OPTIONS",
    "STEP_ORDER",
]

