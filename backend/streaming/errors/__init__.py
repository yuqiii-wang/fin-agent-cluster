"""Streaming workers error code registry package.

Re-exports all error code constants and the ``STREAMING_WORKER_ERRORS``
description dict::

    from backend.streaming.errors import (
        STREAMING_WORKER_ERRORS,
        STREAM_WORKER_BATCH_FAILED,
        STREAM_WORKER_MSG_FAILED,
        STREAM_FALLBACK_MODE,
        STREAM_ORPHAN_DETECTED,
    )
"""

from __future__ import annotations

from backend.streaming.errors.codes import (
    STREAMING_WORKER_ERRORS,
    STREAM_WORKER_BATCH_FAILED,
    STREAM_WORKER_MSG_FAILED,
    STREAM_FALLBACK_MODE,
    STREAM_ORPHAN_DETECTED,
    STREAM_QOS_STALL,
)

__all__ = [
    "STREAMING_WORKER_ERRORS",
    "STREAM_WORKER_BATCH_FAILED",
    "STREAM_WORKER_MSG_FAILED",
    "STREAM_FALLBACK_MODE",
    "STREAM_ORPHAN_DETECTED",
    "STREAM_QOS_STALL",
]
