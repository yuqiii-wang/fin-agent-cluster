"""SSE notifications error code registry.

Covers errors in the lifecycle publish channel and token stream delivery.

Error code prefixes
-------------------
``SSE_``   — SSE notification channel failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: Publishing a lifecycle event to Redis Pub/Sub failed.
SSE_PUBLISH_FAILED = "SSE_PUBLISH_FAILED"

#: Token stream delivery to the SSE generator stalled or failed.
SSE_TOKEN_STREAM_FAILED = "SSE_TOKEN_STREAM_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each SSE notification error code to a human-readable description.
SSE_NOTIFY_ERRORS: dict[str, str] = {
    SSE_PUBLISH_FAILED: (
        "Publishing a lifecycle event to Redis failed. "
        "The SSE client may not receive this event; it will be replayed on reconnect."
    ),
    SSE_TOKEN_STREAM_FAILED: (
        "Token stream delivery encountered an error. "
        "The SSE client may have missed some tokens; check the backend logs."
    ),
}
