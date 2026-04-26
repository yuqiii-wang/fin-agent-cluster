"""Streaming workers error code registry.

Covers errors in Celery stream-consumer workers, the FastAPI fallback mode,
orphan detection, and transmission QoS monitoring.

Error code prefixes
-------------------
``STREAM_WORKER_``  — Celery consumer worker failures.
``STREAM_``         — Streaming orchestration and infrastructure failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Celery worker failures ────────────────────────────────────────────────────

#: A consume_batch() call in a Celery stream worker raised an exception.
STREAM_WORKER_BATCH_FAILED = "STREAM_WORKER_BATCH_FAILED"

#: Processing a single Redis Streams message in a worker raised an exception.
STREAM_WORKER_MSG_FAILED = "STREAM_WORKER_MSG_FAILED"

# ── Streaming orchestration ───────────────────────────────────────────────────

#: Celery workers were not detected at startup; FastAPI fallback threads active.
STREAM_FALLBACK_MODE = "STREAM_FALLBACK_MODE"

#: An orphaned running query was detected (server restarted mid-query).
STREAM_ORPHAN_DETECTED = "STREAM_ORPHAN_DETECTED"

#: TransmissionQoS detected stalled streams above the warning threshold.
STREAM_QOS_STALL = "STREAM_QOS_STALL"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each streaming error code to a human-readable description.
STREAMING_WORKER_ERRORS: dict[str, str] = {
    STREAM_WORKER_BATCH_FAILED: (
        "A Celery stream worker batch failed. "
        "Individual messages in the batch will be retried or skipped."
    ),
    STREAM_WORKER_MSG_FAILED: (
        "A single Redis Streams message could not be processed by the worker. "
        "The message is skipped to preserve stream progress."
    ),
    STREAM_FALLBACK_MODE: (
        "Celery workers were not detected at startup. "
        "The system is running in FastAPI fallback mode — throughput may be reduced."
    ),
    STREAM_ORPHAN_DETECTED: (
        "A query was found in 'running' status with no active asyncio task. "
        "The server likely restarted while the query was executing."
    ),
    STREAM_QOS_STALL: (
        "TransmissionQoS detected stalled token streams. "
        "Some SSE clients may be experiencing delayed delivery."
    ),
}
