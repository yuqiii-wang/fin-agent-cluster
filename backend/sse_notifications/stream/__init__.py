"""stream — SSE notifications for streaming-level lifecycle events.

Leaf level of the event scope hierarchy (thread → node → task → stream).
Events are ephemeral — not persisted in PG DB.  Timestamps are wall-clock
values from the streaming worker.

Emitted events
--------------
``ingest_complete``  — ingest phase finished writing tokens to the Redis stream.
``stream_stopped``   — hard timeout fired before all tokens were streamed.
``stream_complete``  — all requested tokens were successfully streamed.
"""

from backend.sse_notifications.stream.notifications import (
    emit_ingest_complete,
    emit_stream_complete,
    emit_stream_stopped,
)

__all__ = [
    "emit_ingest_complete",
    "emit_stream_stopped",
    "emit_stream_complete",
]
