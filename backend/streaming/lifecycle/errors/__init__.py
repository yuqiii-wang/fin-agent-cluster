"""Streaming lifecycle error code registry package.

Re-exports all error code constants and the ``STREAMING_ERRORS`` description
dict so other modules can import from a single path::

    from backend.streaming.lifecycle.errors import (
        STREAMING_ERRORS,
        GRAPH_EXECUTION_FAILED,
        ORPHAN_SERVER_RESTART,
        DB_INSERT_FAILED,
        # …
    )
"""

from __future__ import annotations

from backend.streaming.lifecycle.errors.codes import (
    DB_INSERT_FAILED,
    GRAPH_EXECUTION_FAILED,
    LLM_INFERENCE_FAILED,
    MARKET_DATA_FETCH_FAILED,
    ORPHAN_SERVER_RESTART,
    PERF_CELERY_REVOKED,
    PERF_INGEST_FAILED,
    PERF_INGEST_TIMEOUT,
    PERF_LOCUST_STREAM_INTERRUPTED,
    PERF_PUBLISH_FAILED,
    QO_EXTRACTION_FAILED,
    STREAMING_ERRORS,
    TASK_EXECUTION_FAILED,
    WEB_SEARCH_FAILED,
)

__all__ = [
    "STREAMING_ERRORS",
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
