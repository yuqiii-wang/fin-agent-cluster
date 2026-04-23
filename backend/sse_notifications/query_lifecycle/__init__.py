"""query_lifecycle — SSE notifications for query-level handshake and phase events.

Emits three events:

  ``query_received``       — backend accepted the query; client must ACK to
                             start graph execution.  Stored in the pending-notify
                             Redis store so the SSE drain cycle retries delivery
                             until the client acks.

  ``query_ack_confirmed``  — backend received the client ACK; LangGraph
                             execution is starting.  Client should stop sending
                             further ACK retries on receipt.

  ``query_status``         — phase transition event for all query types
                             (regular + perf-test).  Previously lived in the
                             perf_test sub-package; consolidated here.
"""

from backend.sse_notifications.query_lifecycle.notifications import (
    emit_query_ack_confirmed,
    emit_query_received,
    emit_query_status,
)

__all__ = [
    "emit_query_received",
    "emit_query_ack_confirmed",
    "emit_query_status",
]
