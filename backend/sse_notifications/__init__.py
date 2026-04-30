"""sse_notifications — centralized SSE notification management.

Service sub-packages
--------------------
``agent_tasks``
    Task lifecycle, control signals and token streaming.
``node_io``
    LangGraph node input/output SSE.
``streamer``
    Streaming lifecycle events (ingest_complete, stream_complete, stream_stopped).

Shared modules
--------------
``channel``    Redis Pub/Sub publish transport.
``schemas``    Pydantic payload models for every SSE event type.
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
    stream_text_task,
)
from backend.sse_notifications.node_io import emit_node_input, emit_node_output
from backend.sse_notifications.streamer import (
    emit_ingest_complete,
    emit_stream_complete,
    emit_stream_stopped,
)
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
    # node_io
    "emit_node_input",
    "emit_node_output",
    # streamer
    "emit_ingest_complete",
    "emit_stream_complete",
    "emit_stream_stopped",
    # query lifecycle
    "emit_query_received",
    "emit_query_ack_confirmed",
    "emit_query_status",
]
