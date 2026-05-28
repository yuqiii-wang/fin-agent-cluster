"""constants.py — Shared numeric constants and step-name strings for the prepare_peers agent loop."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Validation / correlation constants
# ---------------------------------------------------------------------------

# Yahoo Finance period string for stats fetching (≈500 daily bars).
_VALIDATION_PERIOD: str = "2y"

# quant_stats granularity matching the _VALIDATION_PERIOD (daily bars).
_VALIDATION_GRANULARITY: str = "1day"

# Pearson correlation lookback window — 252 ≈ one year of trading days.
_CORR_WINDOW_BARS: int = 252

# Minimum abs(r) for a peer to be classified as "confirmed".
_CORR_THRESHOLD: float = 0.75

# ---------------------------------------------------------------------------
# Step name constants
# ---------------------------------------------------------------------------

STEP_PROPOSE_URL: str = "propose_url"
STEP_NAVIGATE_WEB: str = "navigate_web"
STEP_FETCH_STATS: str = "fetch_stats"
STEP_FILTER_CO_INDEX: str = "filter_co_index"
STEP_CALCULATE_CORR: str = "calculate_corr"
STEP_ANALYZE_CORR: str = "analyze_corr"

# Canonical execution order — must stay in sync with AGENT_STEPS in registry.py.
STEP_ORDER: list[str] = [
    STEP_PROPOSE_URL,
    STEP_NAVIGATE_WEB,
    STEP_FETCH_STATS,
    STEP_FILTER_CO_INDEX,
    STEP_CALCULATE_CORR,
    STEP_ANALYZE_CORR,
]

__all__ = [
    "_VALIDATION_PERIOD",
    "_VALIDATION_GRANULARITY",
    "_CORR_WINDOW_BARS",
    "_CORR_THRESHOLD",
    "STEP_PROPOSE_URL",
    "STEP_NAVIGATE_WEB",
    "STEP_FETCH_STATS",
    "STEP_FILTER_CO_INDEX",
    "STEP_CALCULATE_CORR",
    "STEP_ANALYZE_CORR",
    "STEP_ORDER",
]
