"""Streaming lifecycle package.

Consolidates all SSE streaming lifecycle logic under a single import path.

Modules
-------
events      — Event constants, phase types, and status sets.
watch       — Redis-backed watch registry (which task the client has expanded).
replay      — SSE state replay for late-connecting clients.
orphan      — Orphaned running-query detection and recovery.
done_ack    — Client done-ACK processing.
schemas     — Pydantic models for the SSE streaming HTTP endpoints.

Quick Import Reference
----------------------
::

    from backend.streaming.lifecycle import (
        # Event constants
        LIFECYCLE_EVENTS,
        DONE_PHASE_EVENTS,
        STREAM_EVENTS,
        TERMINAL_QUERY_STATUSES,
        TERMINAL_TASK_STATUSES,
        ACK_REQUIRED_EVENTS,
        StreamLifecyclePhase,
        # Watch registry
        register_watch,
        unregister_watch,
        get_watched_task,
        is_thread_watching,
        # Replay
        replay_existing,
        # Orphan handling
        handle_orphaned_query,
        # Done-ACK
        ack_done,
        # Endpoint schemas
        WatchTaskRequest,
        WatchTaskResponse,
        DoneAckRequest,
        DoneAckResponse,
        RunningTaskInfo,
        StreamingStatusResponse,
    )
"""

from __future__ import annotations

from backend.streaming.lifecycle.done_ack import ack_done
from backend.streaming.lifecycle.events import (
    ACK_REQUIRED_EVENTS,
    DONE_PHASE_EVENTS,
    LIFECYCLE_EVENTS,
    STREAM_EVENTS,
    TERMINAL_QUERY_STATUSES,
    TERMINAL_TASK_STATUSES,
    StreamLifecyclePhase,
)
from backend.streaming.lifecycle.orphan import handle_orphaned_query
from backend.streaming.lifecycle.replay import replay_existing
from backend.streaming.lifecycle.schemas import (
    DoneAckRequest,
    DoneAckResponse,
    RunningTaskInfo,
    StreamingStatusResponse,
    WatchTaskRequest,
    WatchTaskResponse,
)
from backend.streaming.lifecycle.watch import (
    get_watched_task,
    is_thread_watching,
    register_watch,
    unregister_watch,
)

__all__ = [
    # Event constants
    "LIFECYCLE_EVENTS",
    "DONE_PHASE_EVENTS",
    "STREAM_EVENTS",
    "TERMINAL_QUERY_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "ACK_REQUIRED_EVENTS",
    "StreamLifecyclePhase",
    # Watch registry
    "register_watch",
    "unregister_watch",
    "get_watched_task",
    "is_thread_watching",
    # Replay
    "replay_existing",
    # Orphan handling
    "handle_orphaned_query",
    # Done-ACK
    "ack_done",
    # Endpoint schemas
    "WatchTaskRequest",
    "WatchTaskResponse",
    "DoneAckRequest",
    "DoneAckResponse",
    "RunningTaskInfo",
    "StreamingStatusResponse",
]
