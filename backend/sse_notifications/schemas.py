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
  ``completed``          — a sub-task finished with output (pg_notify path)
  ``failed``             — a sub-task failed (pg_notify path)
  ``cancelled``          — a sub-task was cancelled (pg_notify path)
  ``done``               — the entire query session finished (pg_notify path)
  ``ping``               — keep-alive heartbeat (no data payload)

Node I/O service (``backend.sse_notifications.node_io``):
  ``node_input``         — LangGraph node received inputs (pg_notify path)
  ``node_output``        — LangGraph node produced outputs (pg_notify path)

Performance-test service (``backend.sse_notifications.perf_test``):
  ``perf_test_metrics``  — throughput stats after a perf-test run (pg_notify path)
  ``perf_test_complete`` — all requested tokens were streamed for this session (pg_notify path)
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
    "perf_token",
    "perf_ingest_progress",
    "completed",
    "failed",
    "cancelled",
    "done",
    "ping",
    "node_input",
    "node_output",
    "perf_test_metrics",
    "perf_test_stopped",
    "perf_test_complete",
    "perf_ingest_complete",
    "locust_complete",
    "query_status",
]

# Terminal task statuses — events that carry these arrive via pg_notify after commit.
TERMINAL_TASK_EVENTS: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# All lifecycle event types that travel via PostgreSQL NOTIFY.
PG_NOTIFY_EVENTS: frozenset[str] = frozenset(
    {
        "started",
        "completed",
        "failed",
        "cancelled",
        "done",
        "node_input",
        "node_output",
        "perf_test_metrics",
        "perf_test_stopped",
        "perf_test_complete",
        "perf_ingest_complete",
        "locust_complete",
        "query_status",
    }
)


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


# ---------------------------------------------------------------------------
# Performance-test payload model
# ---------------------------------------------------------------------------


class PerfTestMetricsPayload(BaseModel):
    """Payload for the ``perf_test_metrics`` event — throughput statistics.

    Attributes:
        event: Always ``"perf_test_metrics"``.
        total_tokens: Number of tokens produced across all requests.
        elapsed_ms: Wall-clock time in milliseconds for the whole test.
        tokens_per_second: Aggregate tokens per second throughput.
        num_requests: Number of parallel mock-stream requests run.
    """

    event: Literal["perf_test_metrics"] = "perf_test_metrics"
    total_tokens: int
    elapsed_ms: int
    tokens_per_second: float
    num_requests: int


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


__all__ = [
    "SseEventType",
    "TERMINAL_TASK_EVENTS",
    "PG_NOTIFY_EVENTS",
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
    "PerfTestMetricsPayload",
    "PerfTestCompletePayload",
]
