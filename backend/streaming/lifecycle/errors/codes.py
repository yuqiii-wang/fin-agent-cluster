"""Streaming error code registry.

Single source of truth for all structured error codes emitted by the
streaming pipeline.  Each entry maps a string error code to a human-readable
description that is forwarded to the frontend so tooltips and error popups
can display meaningful messages without relying on raw exception strings.

Error code prefixes
-------------------
``GRAPH_``   — Graph execution / runner level (unhandled exceptions).
``TASK_``    — Individual agent task generic failures.
``ORPHAN_``  — Orphan detection / server restart scenarios.
``PERF_``    — Performance-test specific failures.
``MARKET_``  — Market data retrieval failures.
``LLM_``     — LLM inference failures.
``DB_``      — Database operation failures.
``WEB_``     — Web / news search failures.
``QO_``      — Query-optimizer failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Graph runner ─────────────────────────────────────────────────────────────

#: Unhandled exception during LangGraph execution.
GRAPH_EXECUTION_FAILED = "GRAPH_EXECUTION_FAILED"

# ── Generic task ─────────────────────────────────────────────────────────────

#: Generic catch-all for any agent task that failed.
TASK_EXECUTION_FAILED = "TASK_EXECUTION_FAILED"

# ── Orphan / server restart ───────────────────────────────────────────────────

#: Query was running when the backend restarted; session was interrupted.
ORPHAN_SERVER_RESTART = "ORPHAN_SERVER_RESTART"

# ── Performance test ─────────────────────────────────────────────────────────

#: Celery locust worker task was revoked / terminated before completion.
PERF_CELERY_REVOKED = "PERF_CELERY_REVOKED"

#: Locust SSE stream closed before all data was received (incomplete chunked read).
PERF_LOCUST_STREAM_INTERRUPTED = "PERF_LOCUST_STREAM_INTERRUPTED"

#: Ingest phase exceeded the configured time limit.
PERF_INGEST_TIMEOUT = "PERF_INGEST_TIMEOUT"

#: Ingest phase failed with an unexpected error.
PERF_INGEST_FAILED = "PERF_INGEST_FAILED"

#: Publish / digest phase failed with an unexpected error.
PERF_PUBLISH_FAILED = "PERF_PUBLISH_FAILED"

# ── Market data ───────────────────────────────────────────────────────────────

#: One or more market data sub-tasks (OHLCV, volume, bond, etc.) failed.
MARKET_DATA_FETCH_FAILED = "MARKET_DATA_FETCH_FAILED"

# ── LLM ──────────────────────────────────────────────────────────────────────

#: LLM inference call raised an exception.
LLM_INFERENCE_FAILED = "LLM_INFERENCE_FAILED"

# ── Database ──────────────────────────────────────────────────────────────────

#: Database insert of analysis results failed.
DB_INSERT_FAILED = "DB_INSERT_FAILED"

# ── Web / news search ────────────────────────────────────────────────────────

#: News or web search retrieval raised an exception.
WEB_SEARCH_FAILED = "WEB_SEARCH_FAILED"

# ── Query optimizer ───────────────────────────────────────────────────────────

#: Query-optimizer extraction step failed.
QO_EXTRACTION_FAILED = "QO_EXTRACTION_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each error code to a human-readable description.
#: This dict is served by ``GET /stream/errors`` and is embedded inline in
#: SSE ``failed`` and ``done`` event payloads as ``error_description`` so the
#: frontend can display meaningful tooltips without an extra API call.
STREAMING_ERRORS: dict[str, str] = {
    GRAPH_EXECUTION_FAILED: (
        "An unhandled exception occurred during graph execution. "
        "The query session was terminated. Please try submitting again."
    ),
    TASK_EXECUTION_FAILED: (
        "An agent task failed during execution. "
        "Other tasks in the pipeline may have completed; check the node details."
    ),
    ORPHAN_SERVER_RESTART: (
        "The backend server restarted while your query was running. "
        "The session was interrupted — please submit your query again."
    ),
    PERF_CELERY_REVOKED: (
        "The performance-test Celery worker was terminated before completing. "
        "Try running the test again; consider using a shorter duration."
    ),
    PERF_LOCUST_STREAM_INTERRUPTED: (
        "The Locust SSE stream closed unexpectedly before all data was received. "
        "Performance test results may be incomplete."
    ),
    PERF_INGEST_TIMEOUT: (
        "The performance-test ingest phase exceeded the configured time limit. "
        "Reduce the token count or increase the timeout, then retry."
    ),
    PERF_INGEST_FAILED: (
        "The performance-test ingest phase failed with an unexpected error. "
        "Check the backend logs for details."
    ),
    PERF_PUBLISH_FAILED: (
        "The performance-test publish/digest phase failed with an unexpected error. "
        "Check the backend logs for details."
    ),
    MARKET_DATA_FETCH_FAILED: (
        "One or more market data requests failed (price, volume, or fundamental data). "
        "The analysis may be based on partial data."
    ),
    LLM_INFERENCE_FAILED: (
        "The LLM inference step failed. "
        "This may indicate a temporary model unavailability — try again shortly."
    ),
    DB_INSERT_FAILED: (
        "Failed to persist the analysis report to the database. "
        "The response text may still be visible even though saving failed."
    ),
    WEB_SEARCH_FAILED: (
        "The news or web search step failed. "
        "Analysis will proceed without the latest news context."
    ),
    QO_EXTRACTION_FAILED: (
        "The query-optimizer step failed to extract structured parameters. "
        "The pipeline was stopped before market data was fetched."
    ),
}

__all__ = [
    "STREAMING_ERRORS",
    # Code constants
    "GRAPH_EXECUTION_FAILED",
    "TASK_EXECUTION_FAILED",
    "ORPHAN_SERVER_RESTART",
    "PERF_CELERY_REVOKED",
    "PERF_LOCUST_STREAM_INTERRUPTED",
    "PERF_INGEST_TIMEOUT",
    "PERF_INGEST_FAILED",
    "PERF_PUBLISH_FAILED",
    "MARKET_DATA_FETCH_FAILED",
    "LLM_INFERENCE_FAILED",
    "DB_INSERT_FAILED",
    "WEB_SEARCH_FAILED",
    "QO_EXTRACTION_FAILED",
]
