"""Streaming lifecycle event constants and phase types.

Single source of truth for every named lifecycle phase and SSE event category
used across the streaming pipeline.  All other modules import from here so
there is no risk of string drift between the SSE generator, the pending-notify
store, and the frontend.

Constants
---------
StreamLifecyclePhase     — Literal type for backend query phase strings.
LIFECYCLE_EVENTS         — frozenset of event types delivered via Redis Pub/Sub
                           that must be acked and tracked in the pending-notify store.
TERMINAL_QUERY_STATUSES  — frozenset of ``user_queries.status`` values that
                           mean the query is fully done (no further events expected).
TERMINAL_TASK_STATUSES   — frozenset of ``agent_tasks.status`` values that mean
                           a task slot is closed.
DONE_PHASE_EVENTS        — frozenset of event types that signal the *end* of a
                           streaming session (a client receiving any of these
                           should enter the draining phase).
STREAM_EVENTS            — frozenset of event types delivered via Redis Streams
                           (high-frequency, not tracked in pending-notify).
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Backend query phase literal
# ---------------------------------------------------------------------------

#: All valid ``query_status`` phase values emitted by the backend.
StreamLifecyclePhase = Literal[
    "received",   # query persisted, awaiting client ACK
    "preparing",  # LangGraph initialising
    "ingesting",  # perf-test Phase-1: writing tokens to fin:perf stream
    "digesting",  # perf-test Phase-2: reading from fin:perf stream → SSE
    "running",    # generic executing phase (non-perf queries)
    "completed",  # terminal — success
    "failed",     # terminal — error
    "cancelled",  # terminal — user or timeout cancel
]

# ---------------------------------------------------------------------------
# Event category sets
# ---------------------------------------------------------------------------

#: SSE event types delivered via Redis Pub/Sub lifecycle channel.
#: These are tracked in the pending-notify store and must be acked after delivery.
LIFECYCLE_EVENTS: frozenset[str] = frozenset(
    {
        "started",
        "completed",
        "failed",
        "cancelled",
        "done",
        "query_received",
        "query_ack_confirmed",
        "query_status",
        "perf_ingest_progress",
        "perf_ingest_complete",
        "perf_test_stopped",
        "perf_test_complete",
        "node_input",
        "node_output",
    }
)

#: Subset of LIFECYCLE_EVENTS that signal the end of a streaming session.
#: Receiving any of these means the backend considers the query done;
#: the frontend should enter the ``draining`` phase then send a done-ACK.
DONE_PHASE_EVENTS: frozenset[str] = frozenset({"done"})

#: High-frequency events delivered via Redis Streams (NOT via lifecycle channel).
#: These are NOT tracked in the pending-notify store.
STREAM_EVENTS: frozenset[str] = frozenset(
    {
        "token",
        "perf_token_batch",
        "perf_concurrent_status",
        "perf_token",
    }
)

# ---------------------------------------------------------------------------
# Terminal status sets
# ---------------------------------------------------------------------------

#: ``user_queries.status`` values that mean the query is fully terminal.
#: Once a query reaches one of these the SSE generator can emit ``done`` and close.
TERMINAL_QUERY_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled"}
)

#: ``agent_tasks.status`` values that mean a task is no longer running.
TERMINAL_TASK_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled"}
)

# ---------------------------------------------------------------------------
# ACK-required event set (used by the SSE generator and pending-notify store)
# ---------------------------------------------------------------------------

#: Events that must be acked via ``ack_pending_notify`` after SSE delivery.
#: Equal to LIFECYCLE_EVENTS — kept as a separate name for call-site clarity.
ACK_REQUIRED_EVENTS: frozenset[str] = LIFECYCLE_EVENTS


__all__ = [
    "StreamLifecyclePhase",
    "LIFECYCLE_EVENTS",
    "DONE_PHASE_EVENTS",
    "STREAM_EVENTS",
    "TERMINAL_QUERY_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "ACK_REQUIRED_EVENTS",
]
