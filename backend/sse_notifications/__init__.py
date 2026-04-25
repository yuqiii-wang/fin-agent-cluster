"""sse_notifications — centralized SSE notification management.

This package owns **all** SSE event emission logic.  Every event that the
browser receives originates from one of the service sub-packages:

Service sub-packages
--------------------
``agent_tasks``
    Agent task lifecycle, control signals and token streaming:
      - :func:`create_task`          → inserts row, emits ``started``
      - :func:`complete_task`        → updates row, emits ``completed``
      - :func:`fail_task`            → updates row, emits ``failed``
      - :func:`cancel_task`          → updates row, emits ``cancelled``
      - :func:`emit_done`            → emits ``done``, cleans up Redis Stream
      - :func:`stream_text_task`     → publishes ``token`` events via Redis Streams
      - :func:`stream_llm_task`      → same, for ``AIMessageChunk`` iterables
      - :func:`signal_task_control`  → in-process cancel/pass signals

``node_io``
    LangGraph node input/output SSE:
      - :func:`emit_node_input`   → inserts ``node_executions`` row, emits ``node_input``
      - :func:`emit_node_output`  → updates ``node_executions`` row, emits ``node_output``

``perf_test``
    Performance-test throughput metrics:
      - :func:`emit_perf_test_metrics` → emits ``perf_test_metrics``

Shared modules
--------------
``channel``
    Direct Redis Pub/Sub publish transport for lifecycle events.
``schemas``
    Pydantic payload models for every SSE event type.

Usage example
-------------
::

    from backend.sse_notifications import (
        create_task, complete_task, fail_task, cancel_task, emit_done,
        stream_text_task, stream_llm_task,
        signal_task_control, TaskCancelledSignal, TaskPassSignal,
        emit_node_input, emit_node_output,
        publish_lifecycle,
    )
"""

from backend.sse_notifications.channel import publish_lifecycle
from backend.sse_notifications.schemas import (
    CancelledPayload,
    CompletedPayload,
    ConnectedPayload,
    DonePayload,
    FailedPayload,
    NodeInputPayload,
    NodeOutputPayload,
    LIFECYCLE_EVENTS,
    PingPayload,
    QueryAckConfirmedPayload,
    QueryReceivedPayload,
    StartedPayload,
    SseEventType,
    TERMINAL_TASK_EVENTS,
    TaskLifecyclePayload,
    TokenPayload,
)
from backend.sse_notifications.agent_tasks import (
    TaskCancelledSignal,
    TaskControlAction,
    TaskPassSignal,
    _task_signals,
    cancel_task,
    complete_task,
    create_task,
    emit_done,
    fail_task,
    signal_task_control,
    stream_llm_task,
    stream_perf_text_task,
    stream_text_task,
)
from backend.sse_notifications.node_io import emit_node_input, emit_node_output
from backend.sse_notifications.perf_test import emit_perf_ingest_complete, emit_perf_test_complete, emit_perf_test_stopped
from backend.sse_notifications.query_lifecycle import emit_query_received, emit_query_ack_confirmed, emit_query_status

__all__ = [
    # channel
    "publish_lifecycle",
    # schemas — agent tasks
    "SseEventType",
    "TERMINAL_TASK_EVENTS",
    "LIFECYCLE_EVENTS",
    "ConnectedPayload",
    "StartedPayload",
    "TokenPayload",
    "TaskLifecyclePayload",
    "CompletedPayload",
    "FailedPayload",
    "CancelledPayload",
    "DonePayload",
    "PingPayload",
    # schemas — node I/O
    "NodeInputPayload",
    "NodeOutputPayload",
    # schemas — query lifecycle
    "QueryReceivedPayload",
    "QueryAckConfirmedPayload",
    # agent_tasks — lifecycle
    "create_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    "emit_done",
    # agent_tasks — control
    "TaskControlAction",
    "TaskCancelledSignal",
    "TaskPassSignal",
    "signal_task_control",
    "_task_signals",
    # agent_tasks — token stream
    "stream_llm_task",
    "stream_text_task",
    "stream_perf_text_task",
    # node_io
    "emit_node_input",
    "emit_node_output",
    # perf_test
    "emit_perf_test_stopped",
    "emit_perf_test_complete",
    "emit_perf_ingest_complete",
    # query lifecycle
    "emit_query_received",
    "emit_query_ack_confirmed",
    "emit_query_status",
]
