"""thread — SSE notifications for thread-level lifecycle events.

Covers the top level of the event scope hierarchy (thread → node → task → stream).

Emitted events
--------------
``done``                — the entire LangGraph query session finished.
``query_received``      — backend accepted the query; client must ACK to start execution.
``query_ack_confirmed`` — backend received the ACK; LangGraph execution is starting.
``query_status``        — phase-transition event for all query types.
"""

from backend.sse_notifications.thread.notifications import (
    emit_done,
    emit_query_ack_confirmed,
    emit_query_received,
    emit_query_status,
)

__all__ = [
    "emit_done",
    "emit_query_received",
    "emit_query_ack_confirmed",
    "emit_query_status",
]
