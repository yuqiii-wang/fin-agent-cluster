"""Shared error codes for agent pipeline nodes (query / news / stats / merge).

These codes are common to both ``mock_perf`` and ``mock_single`` agents and
are the authoritative source.  Agent-specific error packages re-export from
here.
"""

STREAM_PUBLISH_FAILED: str = "STREAM_PUBLISH_FAILED"
"""Celery stream ingest task failed or timed out."""

STREAM_CANCELLED: str = "STREAM_CANCELLED"
"""Streaming task was cancelled before completion."""

SCHED_COORDINATOR_TIMEOUT: str = "SCHED_COORDINATOR_TIMEOUT"
"""Fanout task never pushed the done_key within the BLPOP deadline.

Likely causes:
- Stream state missing from Redis at dispatch time (HSET/SMEMBERS race).
- All Celery workers saturated: fanout task queued beyond BLPOP deadline.
- Coordinator task crashed before dispatching the fanout.
"""

SCHED_STREAM_STATE_MISSING: str = "SCHED_STREAM_STATE_MISSING"
"""Stream registered in the run set but its per-stream state hash is empty.

Occurs when SMEMBERS returns the stream_id before HSET completes (< 1 ms
race on shard 0).  The coordinator pushes an immediate timeout result so
the FastAPI BLPOP is unblocked instead of waiting 240 s.
"""

QUERY_FAILED: str = "QUERY_FAILED"
"""query_node encountered an unexpected error producing the analysis request."""

NEWS_FAILED: str = "NEWS_FAILED"
"""news_node failed to fetch news articles."""

STATS_FAILED: str = "STATS_FAILED"
"""stats_node failed to fetch market statistics."""

MERGE_FAILED: str = "MERGE_FAILED"
"""merge_node failed to merge data or run the stream ingest."""

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
