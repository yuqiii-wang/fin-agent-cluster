"""SSE notification payload schemas — Pydantic models for every SSE event type.

Every SSE frame emitted by the backend corresponds to one of these models.
They serve as the single source of truth for payload shapes consumed by both
the SSE generator (``backend.api.stream``) and the frontend EventSource
handlers (``sseHandlers.ts``).

Event hierarchy:

Agent-task service (``backend.sse_notifications.agent_tasks``):
  ``connected``          — stream subscription confirmed
  ``started``            — an agent sub-task began
  ``token``              — one LLM output token (high-frequency, Redis Streams path)
  ``completed``          — a sub-task finished with output (lifecycle channel)
  ``failed``             — a sub-task failed (lifecycle channel)
  ``cancelled``          — a sub-task was cancelled (lifecycle channel)
  ``done``               — the entire query session finished (lifecycle channel)
  ``ping``               — keep-alive heartbeat (no data payload)

Node I/O service (``backend.sse_notifications.node_io``):
  ``node_input``         — LangGraph node received inputs (lifecycle channel)
  ``node_output``        — LangGraph node produced outputs (lifecycle channel)

Performance-test service (``backend.sse_notifications.perf_test``):
  ``perf_test_metrics``  — throughput stats after a perf-test run (lifecycle channel)
  ``perf_test_complete`` — all requested tokens were streamed for this session (lifecycle channel)

Query lifecycle service (``backend.sse_notifications.query_lifecycle``):
  ``query_received``       — backend accepted the query; awaiting client ACK (lifecycle + pending store)
  ``query_ack_confirmed``  — backend received ACK; LangGraph execution starting (lifecycle channel)
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# SSE event type literals
# ---------------------------------------------------------------------------

SseEventType = Literal[
    "connected",
    "started",
    "token",
    "token_batch",
    "completed",
    "failed",
    "cancelled",
    "done",
    "ping",
    "node_input",
    "node_output",
    "ingest_complete",
    "stream_stopped",
    "stream_complete",
    "query_status",
    "query_received",
    "query_ack_confirmed",
]

# Terminal task statuses — events that carry these arrive via Redis Pub/Sub after DB commit.
TERMINAL_TASK_EVENTS: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# All lifecycle event types delivered via Redis Pub/Sub.
LIFECYCLE_EVENTS: frozenset[str] = frozenset(
    {
        "started",
        "completed",
        "failed",
        "cancelled",
        "done",
        "node_input",
        "node_output",
        "ingest_complete",
        "stream_stopped",
        "stream_complete",
        "query_status",
        "query_received",
        "query_ack_confirmed",
    }
)

# Backward-compatible alias.
PG_NOTIFY_EVENTS = LIFECYCLE_EVENTS


# ---------------------------------------------------------------------------
# Individual payload models
# ---------------------------------------------------------------------------


class ConnectedPayload(BaseModel):
    """Payload for the ``connected`` event.

    Attributes:
        event: Always ``"connected"``.
        thread_id: The LangGraph thread UUID the client subscribed to.
    """

    event: Literal["connected"] = "connected"
    thread_id: str


class StartedPayload(BaseModel):
    """Payload for the ``started`` event — fired after task row inserted in DB.

    Attributes:
        event: Always ``"started"``.
        task_id: DB primary key of the new task row.
        node_name: Agent node that owns this task (first segment of task_key).
        task_key: Full dot-separated task key, e.g. ``"market_data.ohlcv.1d"``.
        provider: Optional LLM provider name (e.g. ``"ollama"``).
    """

    event: Literal["started"] = "started"
    task_id: int
    node_name: str
    task_key: str
    provider: Optional[str] = None


class TokenPayload(BaseModel):
    """Payload for the ``token`` event — one LLM output chunk via Redis Streams.

    Attributes:
        event: Always ``"token"``.
        task_id: DB primary key of the producing task.
        node_name: Agent node that owns this task.
        task_key: Full dot-separated task key.
        data: The raw token string.
    """

    event: Literal["token"] = "token"
    task_id: int
    node_name: str
    task_key: str
    data: str


class TaskLifecyclePayload(BaseModel):
    """Base payload for terminal task events (completed / failed / cancelled).

    Attributes:
        event: The specific lifecycle terminal event type.
        task_id: DB primary key of the task.
        node_name: Agent node that owns this task.
        task_key: Full dot-separated task key.
        output: Task output dict persisted to DB, or ``{}`` on failure.
    """

    event: Literal["completed", "failed", "cancelled"]
    task_id: int
    node_name: str
    task_key: str
    output: dict[str, Any] = Field(default_factory=dict)


class CompletedPayload(TaskLifecyclePayload):
    """Payload for the ``completed`` event.

    Attributes:
        event: Always ``"completed"``.
    """

    event: Literal["completed"] = "completed"


class FailedPayload(TaskLifecyclePayload):
    """Payload for the ``failed`` event.

    Attributes:
        event: Always ``"failed"``.
    """

    event: Literal["failed"] = "failed"


class CancelledPayload(TaskLifecyclePayload):
    """Payload for the ``cancelled`` event.

    Attributes:
        event: Always ``"cancelled"``.
    """

    event: Literal["cancelled"] = "cancelled"


class DonePayload(BaseModel):
    """Payload for the ``done`` event — entire query session finished.

    Attributes:
        event: Always ``"done"``.
        status: Final session status: ``"completed"``, ``"failed"``, or
            ``"cancelled"``.
        data: Optional excerpt of the final report (first 500 chars).
    """

    event: Literal["done"] = "done"
    status: str
    data: str = ""


class PingPayload(BaseModel):
    """Empty payload for keep-alive ``ping`` events.

    Attributes:
        event: Always ``"ping"``.
    """

    event: Literal["ping"] = "ping"


# ---------------------------------------------------------------------------
# Node I/O payload models
# ---------------------------------------------------------------------------


class NodeInputPayload(BaseModel):
    """Payload for the ``node_input`` event — LangGraph node received state inputs.

    Attributes:
        event: Always ``"node_input"``.
        node_execution_id: DB primary key of the ``NodeExecution`` row.
        node_name: Name of the node (e.g. ``"market_data_collector"``).
        input: Snapshot of the inputs the node received from state.
    """

    event: Literal["node_input"] = "node_input"
    node_execution_id: int
    node_name: str
    input: dict[str, Any] = Field(default_factory=dict)


class NodeOutputPayload(BaseModel):
    """Payload for the ``node_output`` event — LangGraph node produced state outputs.

    Attributes:
        event: Always ``"node_output"``.
        node_execution_id: DB primary key of the ``NodeExecution`` row.
        node_name: Name of the node.
        output: Snapshot of the node's output written to state.
        elapsed_ms: Wall-clock duration of the node in milliseconds.
    """

    event: Literal["node_output"] = "node_output"
    node_execution_id: int
    node_name: str
    output: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0


class PerfTestStoppedPayload(BaseModel):
    """Payload for the ``perf_test_stopped`` event — emitted when the timeout fires.

    Signals the frontend to freeze the metrics panel and display final stats.

    Attributes:
        event: Always ``"perf_test_stopped"``.
        duration_secs: Configured test duration in seconds.
        elapsed_ms: Actual wall-clock elapsed time in milliseconds.
    """

    event: Literal["perf_test_stopped"] = "perf_test_stopped"
    duration_secs: int
    elapsed_ms: int


class PerfTestCompletePayload(BaseModel):
    """Payload for the ``perf_test_complete`` event — all requested tokens were streamed.

    Emitted when the mock producer finishes the full token budget before the
    timeout fires.  Signals the frontend to mark this specific session as
    completed in the grid.

    Attributes:
        event: Always ``"perf_test_complete"``.
        total_tokens: Number of tokens published.
        elapsed_ms: Wall-clock time in milliseconds for the streaming run.
        tps: Tokens per second throughput.
    """

    event: Literal["perf_test_complete"] = "perf_test_complete"
    total_tokens: int
    elapsed_ms: int
    tps: float


class PerfIngestCompletePayload(BaseModel):
    """Payload for the ``perf_ingest_complete`` event — ingest phase finished.

    Emitted by the perf-test node immediately after the ingest phase writes
    all tokens to the Redis perf stream, before the publish phase begins.
    Allows the frontend to freeze the ingest progress display and show the
    final elapsed ingest time.

    Attributes:
        event: Always ``"perf_ingest_complete"``.
        produced: Tokens written to the Redis perf stream.
        stop_reason: ``"completed"`` or ``"timeout"``.
        ingest_ms: Wall-clock milliseconds spent in the ingest phase.
    """

    event: Literal["perf_ingest_complete"] = "perf_ingest_complete"
    produced: int
    stop_reason: str
    ingest_ms: int


# ---------------------------------------------------------------------------
# Query lifecycle payload models
# ---------------------------------------------------------------------------


class QueryReceivedPayload(BaseModel):
    """Payload for the ``query_received`` event.

    Emitted after the backend accepts a new query and persists the row with
    ``status='received'``.  The client must respond with a POST to
    ``/users/query/{thread_id}/ack`` to start graph execution.

    Attributes:
        event: Always ``"query_received"``.
        thread_id: LangGraph thread UUID the query was assigned.
    """

    event: Literal["query_received"] = "query_received"
    thread_id: str


class QueryAckConfirmedPayload(BaseModel):
    """Payload for the ``query_ack_confirmed`` event.

    Emitted after the backend processes the client ACK and launches the
    LangGraph execution.  On receipt the client should stop sending further
    ACK retries.

    Attributes:
        event: Always ``"query_ack_confirmed"``.
        thread_id: LangGraph thread UUID.
    """

    event: Literal["query_ack_confirmed"] = "query_ack_confirmed"
    thread_id: str


__all__ = [
    "SseEventType",
    "TERMINAL_TASK_EVENTS",
    "PG_NOTIFY_EVENTS",  # backward-compat alias for LIFECYCLE_EVENTS
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
    "NodeInputPayload",
    "NodeOutputPayload",
    "PerfIngestCompletePayload",
    "PerfTestCompletePayload",
    "QueryReceivedPayload",
    "QueryAckConfirmedPayload",
]
