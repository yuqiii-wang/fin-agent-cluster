"""Query-optimizer agent error code registry.

These codes are passed as ``error_code=`` to :func:`~backend.sse_notifications.fail_task`
so the frontend receives a structured code in SSE ``failed`` event payloads.

Error code prefixes
-------------------
``QO_``   — Query-optimizer specific failures.

Note: the shared code ``QO_EXTRACTION_FAILED`` lives in
:mod:`backend.streaming.lifecycle.errors.codes` as it is used by the SSE
description registry.  Codes defined here cover the individual task-level
failures that map onto that shared code.
"""

from __future__ import annotations

# Re-export the shared SSE-level code so callers can import from one place.
from backend.streaming.lifecycle.errors import QO_EXTRACTION_FAILED  # noqa: F401

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Task-level failures (map onto QO_EXTRACTION_FAILED in the SSE registry) ──

#: comprehend_basics task failed — LLM produced no or invalid JSON.
QO_COMPREHEND_FAILED = "QO_COMPREHEND_FAILED"

#: validate_basics task failed — JSON correction / region validation failed.
QO_VALIDATE_FAILED = "QO_VALIDATE_FAILED"

#: populate_json task failed — output model construction failed.
QO_POPULATE_FAILED = "QO_POPULATE_FAILED"

#: populate_sec_profile task failed — SEC overview fetch or assembly failed.
QO_SEC_PROFILE_FAILED = "QO_SEC_PROFILE_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each QO task error code to a human-readable description.
QO_AGENT_ERRORS: dict[str, str] = {
    QO_COMPREHEND_FAILED: (
        "The LLM failed to produce a valid JSON response during query comprehension. "
        "The query may be ambiguous or the LLM provider is temporarily unavailable."
    ),
    QO_VALIDATE_FAILED: (
        "Region / industry validation against the static SQL reference data failed. "
        "Check the raw LLM output and the fin_markets.regions table."
    ),
    QO_POPULATE_FAILED: (
        "Building the full QueryOptimizerOutput from static news templates failed. "
        "Ensure fin_markets_consts static data is loaded correctly."
    ),
    QO_SEC_PROFILE_FAILED: (
        "Fetching or assembling the SEC company profile failed. "
        "The ticker may not be listed on a US exchange or the data provider is unavailable."
    ),
}
