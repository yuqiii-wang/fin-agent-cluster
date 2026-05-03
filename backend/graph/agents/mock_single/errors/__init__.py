"""Error codes for the mock_single agent — re-exported from _shared.errors."""

from backend.graph.agents._shared.errors import (
    MERGE_FAILED,
    NEWS_FAILED,
    QUERY_FAILED,
    STATS_FAILED,
    SCHED_COORDINATOR_TIMEOUT,
    SCHED_STREAM_STATE_MISSING,
    STREAM_CANCELLED,
    STREAM_PUBLISH_FAILED,
)

__all__ = [
    "STREAM_PUBLISH_FAILED",
    "STREAM_CANCELLED",
    "SCHED_COORDINATOR_TIMEOUT",
    "SCHED_STREAM_STATE_MISSING",
    "QUERY_FAILED",
    "NEWS_FAILED",
    "STATS_FAILED",
    "MERGE_FAILED",
]
