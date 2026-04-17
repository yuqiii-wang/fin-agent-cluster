"""Task tracking utilities — write sub-task records to DB and emit Redis Pub/Sub events.

Each graph agent uses these helpers to:
  1. Record a task row in ``fin_agents.tasks`` when work starts.
  2. Publish Redis events so SSE subscribers receive real-time updates.
  3. Mark the task completed (with an optional short summary).

Task keys follow the pattern ``<node>.<method>[.<symbol>[.<suffix>]]`` as defined
in :mod:`backend.graph.agents.task_keys`.  The ``node_name`` DB column is derived
from the first dot-separated segment of the task key.

LLM token streaming is also handled here: callers pass an async iterable of
LangChain ``AIMessageChunk`` objects and each non-empty token is forwarded
directly via Redis publish without a DB write (for throughput).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from typing import Literal, Optional

from langchain_core.messages import AIMessageChunk
from sqlalchemy import update

from backend.db.engine import get_session_factory
from backend.db.streaming import notify
from backend.graph.models import AgentTask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task control signals
# ---------------------------------------------------------------------------

TaskControlAction = Literal["cancel", "pass"]

# Maps task_id → pending control action.  Written by the API endpoints,
# consumed (and deleted) by the streaming loops below.
_task_signals: dict[int, str] = {}


class TaskCancelledSignal(Exception):
    """Raised inside a streaming loop when the client cancels the task."""


class TaskPassSignal(Exception):
    """Raised inside a streaming loop when the client passes with partial output.

    Attributes:
        partial_text: The output accumulated before the pass signal arrived.
    """

    def __init__(self, partial_text: str) -> None:
        """Store the partial output accumulated so far.

        Args:
            partial_text: Tokens collected up to the point of the pass signal.
        """
        self.partial_text = partial_text
        super().__init__(partial_text)


def signal_task_control(task_id: int, action: TaskControlAction) -> None:
    """Register a control signal for a currently-streaming task.

    The next iteration of :func:`stream_text_task` or :func:`stream_llm_task`
    for *task_id* will raise :class:`TaskCancelledSignal` or
    :class:`TaskPassSignal` and stop the upstream generator.

    Args:
        task_id: DB primary key of the running task.
        action:  ``"cancel"`` to abort, ``"pass"`` to accept partial output.
    """
    _task_signals[task_id] = action


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


async def cancel_task(
    thread_id: str,
    task_id: int,
    task_key: str,
) -> None:
    """Mark a task cancelled in DB and emit a ``cancelled`` SSE notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key.
        task_key:  Full dot-separated task key (node name is derived from it).
    """
    node = _node_name(task_key)
    output_val: dict = {"cancelled": True}
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(AgentTask)
            .where(AgentTask.id == task_id)
            .values(
                status="cancelled",
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
            "event": "cancelled",
            "output": output_val,
        },
    )


def _check_signal(task_id: int, parts: list[str]) -> None:
    """Consume a pending control signal and raise the appropriate exception.

    Args:
        task_id: DB primary key of the task being streamed.
        parts:   Tokens accumulated so far (used for the pass signal).

    Raises:
        TaskCancelledSignal: When the pending action is ``"cancel"``.
        TaskPassSignal:      When the pending action is ``"pass"``.
    """
    action = _task_signals.pop(task_id, None)
    if action == "cancel":
        raise TaskCancelledSignal()
    if action == "pass":
        raise TaskPassSignal("".join(parts))


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

    On ``asyncio.CancelledError`` the upstream async generator is explicitly
    closed so the HTTP connection to Ollama is torn down immediately, freeing
    the GPU slot before re-raising the exception.

    On :class:`TaskCancelledSignal` or :class:`TaskPassSignal` the loop exits
    early and re-raises so the caller can mark the task accordingly.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key (node name is derived from it).
        chunks:    Async iterable of LangChain ``AIMessageChunk`` objects.

    Returns:
        The fully assembled response text.
    """
    parts: list[str] = []
    aiter = chunks.__aiter__()
    try:
        while True:
            # Check for a control signal before blocking on the next token.
            _check_signal(task_id, parts)
            try:
                chunk = await aiter.__anext__()
            except StopAsyncIteration:
                break
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
    finally:
        # Close the upstream generator so the httpx connection to Ollama is
        # severed immediately on cancellation, releasing GPU memory.
        _task_signals.pop(task_id, None)
        aclose = getattr(aiter, "aclose", None)
        if aclose is not None:
            try:
                await asyncio.shield(aclose())
            except Exception:  # noqa: BLE001
                pass
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

    On ``asyncio.CancelledError`` the upstream async generator is explicitly
    closed so the HTTP connection to Ollama is torn down immediately, freeing
    the GPU slot before re-raising the exception.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the running task.
        task_key:  Full dot-separated task key (node name is derived from it).
        chunks:    Async iterable of plain string tokens.

    Returns:
        The fully assembled response text.
    """
    parts: list[str] = []
    aiter = chunks.__aiter__()
    try:
        while True:
            # Check for a control signal before blocking on the next token.
            _check_signal(task_id, parts)
            try:
                token = await aiter.__anext__()
            except StopAsyncIteration:
                break
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
    finally:
        # Close the upstream generator so the httpx connection to Ollama is
        # severed immediately on cancellation, releasing GPU memory.
        _task_signals.pop(task_id, None)
        aclose = getattr(aiter, "aclose", None)
        if aclose is not None:
            try:
                await asyncio.shield(aclose())
            except Exception:  # noqa: BLE001
                pass
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
