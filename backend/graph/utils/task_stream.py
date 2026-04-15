"""Task tracking utilities — write sub-task records to DB and emit NOTIFY events.

Each graph agent uses these helpers to:
  1. Record a task row in ``fin_agents.tasks`` when work starts.
  2. Emit ``pg_notify`` events so SSE subscribers receive real-time updates.
  3. Mark the task completed (with an optional short summary).

Task keys follow the pattern ``<node>.<method>[.<symbol>[.<suffix>]]`` as defined
in :mod:`backend.graph.agents.task_keys`.  The ``node_name`` DB column is derived
from the first dot-separated segment of the task key.

LLM token streaming is also handled here: callers pass an async iterable of
LangChain ``AIMessageChunk`` objects and each non-empty token is forwarded
directly via ``pg_notify`` without a DB write (for throughput).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from typing import Optional, Union

from langchain_core.messages import AIMessageChunk
from sqlalchemy import update

from backend.db.engine import get_session_factory
from backend.db.streaming import notify
from backend.graph.models import AgentTask

logger = logging.getLogger(__name__)


def _node_name(task_key: str) -> str:
    """Extract the node name from a dot-separated task key.

    Args:
        task_key: Full task key, e.g. ``'market_data_collector.ohlcv.15min'``.

    Returns:
        The first dot-separated segment, e.g. ``'market_data_collector'``.
    """
    return task_key.split(".")[0]


async def create_task(
    thread_id: str,
    task_key: str,
    node_execution_id: Optional[int] = None,
    provider: Optional[str] = None,
) -> int:
    """Insert a running task record and emit a ``started`` notification.

    Args:
        thread_id:         LangGraph thread UUID.
        task_key:          Full dot-separated task key as defined in
                           :mod:`backend.graph.agents.task_keys`, e.g.
                           ``'market_data_collector.ohlcv.15min'``.  The node
                           name is derived from the first segment.
        node_execution_id: FK to the parent ``node_executions`` row (optional).
        provider:          LLM provider name to include in the started event (optional).

    Returns:
        The new task's primary-key ``id``.
    """
    node = _node_name(task_key)
    factory = get_session_factory()
    async with factory() as session:
        task = AgentTask(
            thread_id=thread_id,
            node_name=node,
            task_key=task_key,
            status="running",
            node_execution_id=node_execution_id,
        )
        session.add(task)
        await session.flush()
        task_id: int = task.id
        await session.commit()

    payload: dict = {"task_id": task_id, "node_name": node, "task_key": task_key, "event": "started"}
    if provider:
        payload["provider"] = provider
    await notify(thread_id, payload)
    logger.debug("[task_stream] started task_id=%d key=%s", task_id, task_key)
    return task_id


async def complete_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    output: Optional[dict] = None,
) -> None:
    """Mark a task completed in DB and emit a ``completed`` notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the task to update.
        task_key:  Full dot-separated task key (node name is derived from it).
        output:    Optional dict of task output/result data.
    """
    node = _node_name(task_key)
    output_val = output or {}
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(AgentTask)
            .where(AgentTask.id == task_id)
            .values(
                status="completed",
                output=output_val,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    await notify(
        thread_id,
        {
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
            "event": "completed",
            "output": output_val,
        },
    )


async def fail_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    error: str,
) -> None:
    """Mark a task failed in DB and emit a ``failed`` notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key.
        task_key:  Full dot-separated task key (node name is derived from it).
        error:     Error message string.
    """
    node = _node_name(task_key)
    output_val = {"error": error[:500]}
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(AgentTask)
            .where(AgentTask.id == task_id)
            .values(
                status="failed",
                output=output_val,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    await notify(
        thread_id,
        {
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
            "event": "failed",
            "output": output_val,
        },
    )


async def stream_llm_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    chunks: AsyncIterable[AIMessageChunk],
) -> str:
    """Consume an LLM async-stream, emit ``token`` notifications, and return full text.

    Each non-empty token in *chunks* is forwarded as a ``pg_notify`` without a
    DB write so throughput is not limited by database round-trips.  Only the
    final ``complete_task`` call persists a text snippet.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key (node name is derived from it).
        chunks:    Async iterable of LangChain ``AIMessageChunk`` objects.

    Returns:
        The fully assembled response text.
    """
    parts: list[str] = []
    async for chunk in chunks:
        token: str = chunk.content  # type: ignore[assignment]
        if token:
            parts.append(token)
            await notify(
                thread_id,
                {
                    "task_id": task_id,
                    "node_name": _node_name(task_key),
                    "task_key": task_key,
                    "event": "token",
                    "data": token,
                },
            )
    return "".join(parts)


async def stream_text_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    chunks: AsyncIterable[str],
) -> str:
    """Consume a plain-text async-stream, emit ``token`` notifications, and return full text.

    Identical to :func:`stream_llm_task` but accepts ``str`` chunks (e.g.
    from a chain that includes ``StrOutputParser``).

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key (node name is derived from it).
        chunks:    Async iterable of plain string tokens.

    Returns:
        The fully assembled response text.
    """
    parts: list[str] = []
    async for token in chunks:
        if token:
            parts.append(token)
            await notify(
                thread_id,
                {
                    "task_id": task_id,
                    "node_name": _node_name(task_key),
                    "task_key": task_key,
                    "event": "token",
                    "data": token,
                },
            )
    return "".join(parts)


async def emit_done(thread_id: str, status: str, report: str = "") -> None:
    """Emit a terminal ``done`` SSE event for *thread_id*.

    Called once after the entire graph finishes (success or failure) so the
    frontend knows the session is over and can close the SSE connection.

    Args:
        thread_id: LangGraph thread UUID.
        status:    ``"completed"`` or ``"failed"``.
        report:    Optional short excerpt of the final report (first 500 chars).
    """
    await notify(
        thread_id,
        {"event": "done", "status": status, "data": report[:500] if report else ""},
    )
