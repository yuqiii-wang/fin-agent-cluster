"""Market-data agent error code registry.

These codes are passed as ``error_code=`` to :func:`~backend.sse_notifications.fail_task`
or embedded in node-level error payloads.

Error code prefixes
-------------------
``MD_``   — Market-data collector specific failures.

Note: the shared SSE-level code ``MARKET_DATA_FETCH_FAILED`` lives in
:mod:`backend.streaming.lifecycle.errors.codes`.  Codes here cover node-level
failures that do not map to any individual task fetch.
"""

from __future__ import annotations

# Re-export the shared SSE-level code so callers can import from one place.
from backend.streaming.lifecycle.errors import MARKET_DATA_FETCH_FAILED  # noqa: F401

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: No ticker could be resolved from the query optimizer output.
MD_NO_TICKER = "MD_NO_TICKER"

#: Parsing the QueryOptimizerOutput from the graph state failed.
MD_PARSE_FAILED = "MD_PARSE_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each MD node error code to a human-readable description.
MD_AGENT_ERRORS: dict[str, str] = {
    MD_NO_TICKER: (
        "No ticker symbol could be resolved from the query optimizer output. "
        "The query may refer to an unknown or ambiguous instrument."
    ),
    MD_PARSE_FAILED: (
        "Parsing the QueryOptimizerOutput from the graph state failed. "
        "The upstream query_optimizer node may have produced invalid output."
    ),
}
