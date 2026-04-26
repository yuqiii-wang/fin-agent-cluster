"""SSE notifications error code registry package.

Re-exports all error code constants and the ``SSE_NOTIFY_ERRORS`` description dict::

    from backend.sse_notifications.errors import (
        SSE_NOTIFY_ERRORS,
        SSE_PUBLISH_FAILED,
        SSE_TOKEN_STREAM_FAILED,
    )
"""

from __future__ import annotations

from backend.sse_notifications.errors.codes import (
    SSE_NOTIFY_ERRORS,
    SSE_PUBLISH_FAILED,
    SSE_TOKEN_STREAM_FAILED,
)

__all__ = [
    "SSE_NOTIFY_ERRORS",
    "SSE_PUBLISH_FAILED",
    "SSE_TOKEN_STREAM_FAILED",
]
