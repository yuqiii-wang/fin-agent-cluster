"""Pydantic schemas for the SSE streaming HTTP endpoints.

These models are used by the request/response handlers in
``backend.api.stream`` — they are distinct from the Redis Streams message
schemas in ``backend.streaming.schemas`` which describe topic payloads.
"""

from __future__ import annotations

from pydantic import BaseModel


class WatchTaskRequest(BaseModel):
    """Body for ``PUT /stream/{thread_id}/watch``.

    Attributes:
        task_id: The task the client has expanded (``None`` to unwatch).
    """

    task_id: int | None = None


class WatchTaskResponse(BaseModel):
    """Response for ``PUT /stream/{thread_id}/watch``.

    Attributes:
        thread_id: Echo of the thread.
        task_id:   The registered task_id, or ``None`` if unwatched.
    """

    thread_id: str
    task_id: int | None


class DoneAckRequest(BaseModel):
    """Body for ``POST /stream/{thread_id}/done-ack``.

    Sent by the frontend after the ``DoneConditionGuard`` has resolved — i.e.
    all drain conditions (tasks terminal, token count satisfied) have been met
    or the drain window expired.

    Attributes:
        status: The terminal status the client observed and confirmed, e.g.
                ``"completed"``, ``"failed"``, ``"timeout"``.
    """

    status: str


class DoneAckResponse(BaseModel):
    """Response for ``POST /stream/{thread_id}/done-ack``.

    Attributes:
        acknowledged: Always ``True`` when the request succeeds.
        thread_id:    Echo of the thread that was acknowledged.
    """

    acknowledged: bool
    thread_id: str


class RunningTaskInfo(BaseModel):
    """Minimal task info item inside :class:`StreamingStatusResponse`.

    Attributes:
        task_id:   DB primary key of the task.
        task_key:  Dot-delimited task key, e.g. ``market_data_collector.fetch``.
        node_name: Graph node the task belongs to.
    """

    task_id: int
    task_key: str
    node_name: str


class StreamingStatusResponse(BaseModel):
    """Health snapshot for an active streaming session.

    Returned by ``GET /stream/{thread_id}/status``.  Intended to be polled by
    the frontend when no ``token`` SSE event has been received for ≥ 5 seconds
    while the session is still in loading state.

    Attributes:
        thread_id:          LangGraph thread UUID.
        query_status:       Current ``user_queries.status`` (``running``,
                            ``completed``, etc.).
        running_tasks:      Tasks whose DB status is still ``'running'``.
        last_token_ms_ago:  Milliseconds since the most-recent token was
                            published to Redis Streams; ``None`` if the stream
                            key no longer exists.
        is_active:          ``True`` if an asyncio.Task is registered in the
                            in-memory registry and has not finished.
    """

    thread_id: str
    query_status: str
    running_tasks: list[RunningTaskInfo]
    last_token_ms_ago: int | None
    is_active: bool


class StreamingErrorsResponse(BaseModel):
    """Response for ``GET /stream/errors``.

    Returns the full backend error code → description registry so the frontend
    can display meaningful tooltips for structured ``error_code`` values that
    arrive in SSE ``failed`` and ``done`` payloads.

    Attributes:
        errors: Mapping of error code string → human-readable description.
    """

    errors: dict[str, str]


__all__ = [
    "WatchTaskRequest",
    "WatchTaskResponse",
    "DoneAckRequest",
    "DoneAckResponse",
    "RunningTaskInfo",
    "StreamingStatusResponse",
    "StreamingErrorsResponse",
]
