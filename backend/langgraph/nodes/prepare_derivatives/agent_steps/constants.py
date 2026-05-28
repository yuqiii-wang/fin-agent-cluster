"""constants.py — Step-name constants for the prepare_derivatives agent steps."""

from __future__ import annotations

STEP_PROPOSE_URL: str = "propose_url"
STEP_NAVIGATE_WEB: str = "navigate_web"
STEP_GET_STATS: str = "get_stats"

# Canonical execution order.
STEP_ORDER: list[str] = [STEP_PROPOSE_URL, STEP_NAVIGATE_WEB, STEP_GET_STATS]

__all__ = [
    "STEP_PROPOSE_URL",
    "STEP_NAVIGATE_WEB",
    "STEP_GET_STATS",
    "STEP_ORDER",
]
