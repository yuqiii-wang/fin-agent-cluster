"""Decision-maker agent error code registry.

These codes are passed as ``error_code=`` to :func:`~backend.sse_notifications.fail_task`
or embedded in node-level error payloads.

Error code prefixes
-------------------
``DM_``   — Decision-maker specific failures.

Note: the shared SSE-level codes ``LLM_INFERENCE_FAILED`` and ``DB_INSERT_FAILED``
live in :mod:`backend.streaming.lifecycle.errors.codes`.
"""

from __future__ import annotations

# Re-export shared SSE-level codes so callers can import from one place.
from backend.streaming.lifecycle.errors import (  # noqa: F401
    DB_INSERT_FAILED,
    LLM_INFERENCE_FAILED,
)

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: No market data was available in the graph state for the decision maker.
DM_NO_MARKET_DATA = "DM_NO_MARKET_DATA"

#: Parsing the MarketDataOutput from the graph state failed.
DM_PARSE_FAILED = "DM_PARSE_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each DM node error code to a human-readable description.
DM_AGENT_ERRORS: dict[str, str] = {
    DM_NO_MARKET_DATA: (
        "No market data was available for the decision-maker node. "
        "The market_data_collector node may have failed or returned empty results."
    ),
    DM_PARSE_FAILED: (
        "Parsing the MarketDataOutput from the graph state failed. "
        "The upstream market_data_collector node may have produced invalid output."
    ),
}
