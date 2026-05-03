"""sse_notifications — centralized SSE notification management.

Scope hierarchy
---------------
``thread``   Top-level session events (done, query_received, query_ack_confirmed, query_status).
``node``     Node-level I/O and status events (node_input, node_output, node_status).
``task``     Task CRUD lifecycle, control signals and token streaming.
``stream``   Ephemeral streaming lifecycle events (ingest_complete, stream_complete, stream_stopped).

Shared modules
--------------
``channel``    Scope-based Centrifugo publish transport (thread / node / task / stream).
``schemas``    Pydantic payload models for every SSE event type.
"""

from backend.sse_notifications.channel import (
    publish_node_lifecycle,
    publish_stream_lifecycle,
    publish_task_lifecycle,
    publish_thread_lifecycle,
)
from backend.sse_notifications.schemas import (
    CancelledPayload,
    CompletedPayload,
    ConnectedPayload,
    DonePayload,
    FailedPayload,
    NodeInputPayload,
    NodeOutputPayload,
    NodeStatusPayload,
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
from backend.sse_notifications.thread import (
    emit_done,
    emit_query_received,
    emit_query_ack_confirmed,
    emit_query_status,
)
from backend.sse_notifications.node import emit_node_input, emit_node_output, emit_node_status
from backend.sse_notifications.task import (
    TaskCancelledSignal,
    TaskControlAction,
    TaskPassSignal,
    _task_signals,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
    signal_task_control,
    stream_llm_task,
    stream_text_task,
)
from backend.sse_notifications.stream import (
    emit_ingest_complete,
    emit_stream_complete,
    emit_stream_stopped,
)

__all__ = [
    # channel — scope-based publishers
    "publish_thread_lifecycle",
    "publish_node_lifecycle",
    "publish_task_lifecycle",
    "publish_stream_lifecycle",
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
    "NodeStatusPayload",
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
    # node_io
    "emit_node_input",
    "emit_node_output",
    "emit_node_status",
    # mock
    "emit_ingest_complete",
    "emit_stream_complete",
    "emit_stream_stopped",
    # query lifecycle
    "emit_query_received",
    "emit_query_ack_confirmed",
    "emit_query_status",
]

