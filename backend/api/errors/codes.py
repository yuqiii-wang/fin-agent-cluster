"""API layer error code registry.

Error code prefixes
-------------------
``API_QUERY_``   — User query lifecycle errors (not found, status conflict).
``API_TASK_``    — Agent task control errors.
``API_STREAM_``  — SSE / streaming endpoint errors.
``API_QUANT_``   — Quant stats / indicator endpoint errors.
``API_REPORT_``  — Report retrieval errors.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Query lifecycle ──────────────────────────────────────────────────────────

#: Query thread_id not found in the database.
API_QUERY_NOT_FOUND = "API_QUERY_NOT_FOUND"

#: ACK / cancel attempted on a query in a non-actionable status.
API_QUERY_STATUS_CONFLICT = "API_QUERY_STATUS_CONFLICT"

# ── Task control ─────────────────────────────────────────────────────────────

#: task_id path parameter is not a positive integer.
API_TASK_ID_INVALID = "API_TASK_ID_INVALID"

# ── Streaming / SSE ──────────────────────────────────────────────────────────

#: Requested Redis stream key is not in the allowed set.
API_STREAM_UNKNOWN_KEY = "API_STREAM_UNKNOWN_KEY"

#: Redis XREAD call failed during SSE stream delivery.
API_STREAM_READ_FAILED = "API_STREAM_READ_FAILED"

# ── Quant stats ───────────────────────────────────────────────────────────────

#: Requested bar granularity is not in the valid set (15min, 1h, 1day, 1mo).
API_QUANT_INVALID_GRANULARITY = "API_QUANT_INVALID_GRANULARITY"

#: instrument_type is not 'equity' or 'index'.
API_QUANT_INVALID_INSTRUMENT = "API_QUANT_INVALID_INSTRUMENT"

#: Requested indicator id is not in the static registry.
API_QUANT_UNKNOWN_INDICATOR = "API_QUANT_UNKNOWN_INDICATOR"

#: Indicator column mapping is missing from the server-side whitelist.
API_QUANT_CONFIG_ERROR = "API_QUANT_CONFIG_ERROR"

#: Database query for quant stats failed.
API_QUANT_DB_FAILED = "API_QUANT_DB_FAILED"

#: No currency data found for the requested symbol.
API_QUANT_NO_CURRENCY = "API_QUANT_NO_CURRENCY"

# ── Reports ───────────────────────────────────────────────────────────────────

#: Report not found for the requested symbol or report_id.
API_REPORT_NOT_FOUND = "API_REPORT_NOT_FOUND"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each error code to a human-readable description forwarded to clients.
API_ERRORS: dict[str, str] = {
    API_QUERY_NOT_FOUND: (
        "The requested query thread was not found. "
        "It may have expired or the thread_id is incorrect."
    ),
    API_QUERY_STATUS_CONFLICT: (
        "The query cannot be acknowledged or cancelled in its current status. "
        "Check the current status and retry if appropriate."
    ),
    API_TASK_ID_INVALID: (
        "The task_id must be a positive integer."
    ),
    API_STREAM_UNKNOWN_KEY: (
        "The requested Redis stream key is not recognised. "
        "Use one of the supported stream keys."
    ),
    API_STREAM_READ_FAILED: (
        "Failed to read from the Redis stream. "
        "The stream service may be temporarily unavailable."
    ),
    API_QUANT_INVALID_GRANULARITY: (
        "The requested bar granularity is not supported. "
        "Valid values: 15min, 1h, 1day, 1mo."
    ),
    API_QUANT_INVALID_INSTRUMENT: (
        "instrument_type must be 'equity' or 'index'."
    ),
    API_QUANT_UNKNOWN_INDICATOR: (
        "The requested indicator id is not in the registry. "
        "Use GET /quant/indicators to retrieve valid ids."
    ),
    API_QUANT_CONFIG_ERROR: (
        "Internal configuration error: indicator column mapping is missing. "
        "Contact support."
    ),
    API_QUANT_DB_FAILED: (
        "The quant stats database query failed. "
        "Retry the request; if the problem persists check the backend logs."
    ),
    API_QUANT_NO_CURRENCY: (
        "No currency data was found for the requested symbol."
    ),
    API_REPORT_NOT_FOUND: (
        "The requested analysis report was not found. "
        "The symbol may not have any completed reports yet."
    ),
}
