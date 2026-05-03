"""Service logic for the threads read/event API.

Provides DB-only queries and event-emit helpers that do **not** trigger
a LangGraph graph run.  All writes are direct SQL updates; events reach
the browser via :func:`~backend.sse_notifications.channel.publish_thread_lifecycle`.

Functions
---------
``list_threads``          — paginated list of user_queries rows
``get_thread_llm_responses`` — LLM completion records for a thread
``get_thread_state``      — LangGraph checkpoint state (read-only aget_state)
``update_thread_status``  — UPDATE user_queries.status + optional event
``emit_thread_event``     — publish any lifecycle payload to Centrifugo
``resync_thread``         — re-emit current task/query state from DB
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.api.errors import (
    API_QUERY_NOT_FOUND,
    API_THREAD_EMIT_INVALID_EVENT,
    API_THREAD_STATUS_INVALID,
)
from backend.db import get_session_factory as _get_session_factory, raw_conn
from backend.graph.models import AgentTask
from backend.sse_notifications.channel import publish_task_lifecycle, publish_thread_lifecycle
from backend.sse_notifications.thread import emit_query_status
from backend.users.models import UserQuery
from backend.users.schemas import (
    EmitEventResponse,
    LlmResponseList,
    LlmResponseRecord,
    ResyncResponse,
    ThreadListResponse,
    ThreadStateResponse,
    ThreadSummary,
    UpdateThreadStatusResponse,
)

logger = logging.getLogger(__name__)

# Statuses that callers are allowed to set via the update endpoint.
_VALID_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)

# Event types allowed via the manual emit endpoint — excludes high-frequency
# stream events (token / perf_token) which travel via Redis Streams.
_ALLOWED_EMIT_EVENTS: frozenset[str] = frozenset(
    {
        "connected",
        "started",
        "completed",
        "failed",
        "cancelled",
        "done",
        "ping",
        "node_input",
        "node_output",
        "token_batch",
        "ingest_complete",
        "stream_stopped",
        "stream_complete",
        "query_status",
        "query_received",
        "query_ack_confirmed",
    }
)


async def list_threads(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> ThreadListResponse:
    """Return a paginated list of user query threads.

    Args:
        user_id: Filter to a specific user (optional).
        status:  Comma-separated status values to filter on (optional).
        limit:   Page size (1–100, default 20).
        offset:  Row offset for pagination.

    Returns:
        :class:`~backend.users.schemas.ThreadListResponse`.
    """
    factory = _get_session_factory()
    async with factory() as session:
        q = select(UserQuery).order_by(UserQuery.created_at.desc())
        count_q = select(func.count()).select_from(UserQuery)

        if user_id:
            q = q.where(UserQuery.user_id == user_id)
            count_q = count_q.where(UserQuery.user_id == user_id)

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            q = q.where(UserQuery.status.in_(statuses))
            count_q = count_q.where(UserQuery.status.in_(statuses))

        total: int = await session.scalar(count_q) or 0
        result = await session.execute(q.limit(limit).offset(offset))
        rows = result.scalars().all()

    items = [
        ThreadSummary(
            thread_id=r.thread_id,
            query=r.query,
            status=r.status,
            created_at=r.created_at,
            completed_at=r.completed_at,
            answer=r.answer,
        )
        for r in rows
    ]
    return ThreadListResponse(items=items, total=total, limit=limit, offset=offset)


async def get_thread_llm_responses(
    thread_id: str,
    limit: int = 50,
    offset: int = 0,
) -> LlmResponseList:
    """Return LLM completion records for *thread_id* from ``fin_agents.llm_responses``.

    Args:
        thread_id: LangGraph thread UUID.
        limit:     Max records to return (1–200, default 50).
        offset:    Row offset for pagination.

    Returns:
        :class:`~backend.users.schemas.LlmResponseList`.

    Raises:
        404: Thread not found.
    """
    await _require_thread(thread_id)

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT id, event_id, ts, provider, model, task_name, node_name,
                   prompt_tokens, completion_tokens, total_tokens, latency_ms,
                   thinking, answer
            FROM fin_agents.llm_responses
            WHERE thread_id = %s
            ORDER BY ts DESC
            LIMIT %s OFFSET %s
            """,
            (thread_id, limit, offset),
        )
        rows = await cur.fetchall()

    records = [
        LlmResponseRecord(
            id=r["id"],
            event_id=r["event_id"],
            ts=r["ts"],
            provider=r["provider"],
            model=r["model"],
            task_name=r["task_name"],
            node_name=r["node_name"],
            prompt_tokens=r["prompt_tokens"],
            completion_tokens=r["completion_tokens"],
            total_tokens=r["total_tokens"],
            latency_ms=r["latency_ms"],
            thinking=r["thinking"],
            answer=r["answer"],
        )
        for r in rows
    ]
    return LlmResponseList(thread_id=thread_id, records=records)


async def get_thread_state(thread_id: str) -> ThreadStateResponse:
    """Return the latest LangGraph checkpoint state for *thread_id*.

    Uses ``CompiledStateGraph.aget_state`` which is a pure read from the
    PostgreSQL checkpointer — **no graph nodes execute**.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`~backend.users.schemas.ThreadStateResponse` with the latest
        state dict and checkpoint_id, or an empty state when no checkpoint exists.

    Raises:
        404: Thread not found.
    """
    await _require_thread(thread_id)

    from backend.graph.compiled import get_compiled_graph  # noqa: PLC0415

    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)

    checkpoint_id: Optional[str] = None
    state_values: dict[str, Any] = {}

    if snapshot is not None:
        checkpoint_id = (snapshot.config or {}).get("configurable", {}).get("checkpoint_id")
        state_values = dict(snapshot.values) if snapshot.values else {}

    return ThreadStateResponse(
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        state=state_values,
    )


async def update_thread_status(
    thread_id: str,
    status: str,
    error: Optional[str] = None,
    emit_event: bool = True,
) -> UpdateThreadStatusResponse:
    """Update a thread's status in DB without triggering a graph run.

    Args:
        thread_id:   LangGraph thread UUID.
        status:      New status — must be one of ``pending / running /
                     completed / failed / cancelled``.
        error:       Optional error message to persist alongside the status.
        emit_event:  When ``True``, publish a ``query_status`` event via
                     Centrifugo after committing.

    Returns:
        :class:`~backend.users.schemas.UpdateThreadStatusResponse`.

    Raises:
        404: Thread not found.
        422: Status value is not in the allowed set.
    """
    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": API_THREAD_STATUS_INVALID,
                "message": f"Invalid status '{status}'. Allowed: {sorted(_VALID_STATUSES)}",
            },
        )

    factory = _get_session_factory()
    async with factory() as session:
        row = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": API_QUERY_NOT_FOUND, "message": "Thread not found"},
            )
        row.status = status
        if error is not None:
            row.error = error
        if status in ("completed", "failed", "cancelled"):
            row.completed_at = datetime.utcnow()
        await session.commit()

    logger.info(
        "[threads] status_updated thread_id=%s status=%s", thread_id, status
    )

    event_emitted = False
    if emit_event:
        await emit_query_status(thread_id, status)
        event_emitted = True

    return UpdateThreadStatusResponse(
        thread_id=thread_id,
        status=status,
        event_emitted=event_emitted,
    )


async def emit_thread_event(
    thread_id: str,
    event: str,
    payload: dict[str, Any],
) -> EmitEventResponse:
    """Publish a lifecycle event to the thread's Centrifugo channel.

    Does **not** write to the database.  Use this to replay events to
    reconnecting clients or to inject synthetic events for debugging.

    Args:
        thread_id: LangGraph thread UUID.
        event:     Event type — must be in the allowed lifecycle set.
        payload:   Extra fields merged into the published payload.

    Returns:
        :class:`~backend.users.schemas.EmitEventResponse`.

    Raises:
        404: Thread not found.
        422: Event type is not allowed via this endpoint.
    """
    if event not in _ALLOWED_EMIT_EVENTS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": API_THREAD_EMIT_INVALID_EVENT,
                "message": (
                    f"Event '{event}' is not allowed via this endpoint. "
                    f"Allowed: {sorted(_ALLOWED_EMIT_EVENTS)}"
                ),
            },
        )

    await _require_thread(thread_id)

    full_payload: dict[str, Any] = {**payload, "event": event, "thread_id": thread_id}
    await publish_thread_lifecycle(thread_id, full_payload)

    logger.info(
        "[threads] manual_event_emitted event=%s thread_id=%s", event, thread_id
    )
    return EmitEventResponse(thread_id=thread_id, event=event, published=True)


async def resync_thread(thread_id: str) -> ResyncResponse:
    """Re-emit current thread and task states as Centrifugo events.

    Reads the current DB state and publishes one ``query_status`` event for
    the thread and one ``started`` / ``completed`` / ``failed`` / ``cancelled``
    event per task.  Intended for clients that reconnect mid-session and need
    to catch up without replaying the full Centrifugo history.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`~backend.users.schemas.ResyncResponse` with count of events
        emitted.

    Raises:
        404: Thread not found.
    """
    factory = _get_session_factory()
    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if uq is None:
            raise HTTPException(
                status_code=404,
                detail={"code": API_QUERY_NOT_FOUND, "message": "Thread not found"},
            )

        tasks_result = await session.execute(
            select(AgentTask)
            .where(AgentTask.thread_id == thread_id)
            .order_by(AgentTask.created_at)
        )
        task_rows = tasks_result.scalars().all()

    emitted = 0

    # Re-emit the current query phase.
    await emit_query_status(thread_id, uq.status)
    emitted += 1

    # Re-emit each task's terminal (or running) state.
    for task in task_rows:
        event = _task_status_to_event(task.status)
        await publish_task_lifecycle(
            thread_id,
            {
                "event": event,
                "thread_id": thread_id,
                "task_id": task.task_id,
                "task_name": task.task_name,
                "node_name": task.node_name,
                "status": task.status,
                "output": task.output,
            },
        )
        emitted += 1

    logger.info(
        "[threads] resync_emitted thread_id=%s events=%d", thread_id, emitted
    )
    return ResyncResponse(thread_id=thread_id, events_emitted=emitted)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_thread(thread_id: str) -> None:
    """Raise HTTP 404 when *thread_id* does not exist in user_queries."""
    factory = _get_session_factory()
    async with factory() as session:
        exists = await session.scalar(
            select(UserQuery.thread_id).where(UserQuery.thread_id == thread_id)
        )
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail={"code": API_QUERY_NOT_FOUND, "message": "Thread not found"},
        )


def _task_status_to_event(status: str) -> str:
    """Map a task DB status to the corresponding SSE event type.

    Args:
        status: Task status string from ``fin_agents.tasks``.

    Returns:
        SSE event type string.
    """
    _MAP = {
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "running": "started",
        "pending": "started",
        "received": "started",
    }
    return _MAP.get(status, "started")
