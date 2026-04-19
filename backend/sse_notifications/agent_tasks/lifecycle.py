"""Task lifecycle SSE notifications — DB writes + pg_notify emission.

Every public function in this module follows the same pattern:
  1. Write the new task state to ``fin_agents.tasks`` in PostgreSQL.
  2. Commit the transaction.
  3. Fire ``pg_notify`` on the thread's channel so SSE subscribers receive
     an authoritative, durable event payload.

Only lifecycle events travel through this path.  Token events use the Redis
Streams path (see :mod:`backend.sse_notifications.agent_tasks.token_stream`).

``AgentTask`` is imported lazily inside each function to break the circular
dependency: ``sse_notifications`` ← ``backend.graph`` (package) ← agents ←
``sse_notifications``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update

from backend.db.postgres.engine import get_session_factory
from backend.db.redis.publisher import delete_stream
from backend.sse_notifications.channel import pg_notify

logger = logging.getLogger(__name__)


def _node_name(task_key: str) -> str:
    """Extract the agent node name from a dot-separated task key.

    Args:
        task_key: Full task key, e.g. ``"market_data_collector.ohlcv.15min"``.

    Returns:
        First dot-separated segment, e.g. ``"market_data_collector"``.
    """
    return task_key.split(".")[0]


async def create_task(
    thread_id: str,
    task_key: str,
    node_execution_id: Optional[int] = None,
    provider: Optional[str] = None,
) -> int:
    """Insert a running task record in DB and emit a ``started`` SSE notification.

    Must be called at the beginning of each agent sub-task.  The returned
    ``task_id`` is used by subsequent lifecycle and token calls.

    Args:
        thread_id:         LangGraph thread UUID.
        task_key:          Full dot-separated task key, e.g.
                           ``"market_data_collector.ohlcv.15min"``.
        node_execution_id: FK to the parent ``node_executions`` row (optional).
        provider:          LLM provider name to include in the ``started``
                           payload (optional).

    Returns:
        DB primary key of the newly created task row.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

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

    payload: dict = {
        "event": "started",
        "task_id": task_id,
        "node_name": node,
        "task_key": task_key,
    }
    if provider:
        payload["provider"] = provider
    await pg_notify(thread_id, payload)
    logger.info(
        "[task_lifecycle] created task_id=%d key=%s node=%s thread_id=%s",
        task_id,
        task_key,
        node,
        thread_id,
    )
    return task_id


async def complete_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    output: Optional[dict] = None,
) -> None:
    """Mark a task completed in DB and emit a ``completed`` SSE notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the task row to update.
        task_key:  Full dot-separated task key.
        output:    Optional result dict persisted to ``tasks.output``.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

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

    await pg_notify(
        thread_id,
        {
            "event": "completed",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
            "output": output_val,
        },
    )


async def fail_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    error: str,
) -> None:
    """Mark a task failed in DB and emit a ``failed`` SSE notification.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the task row.
        task_key:  Full dot-separated task key.
        error:     Error message string (truncated to 500 chars in output).
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

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

    await pg_notify(
        thread_id,
        {
            "event": "failed",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
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
        task_id:   DB primary key of the task row.
        task_key:  Full dot-separated task key.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

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

    await pg_notify(
        thread_id,
        {
            "event": "cancelled",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
            "output": output_val,
        },
    )


async def emit_done(thread_id: str, status: str, report: str = "") -> None:
    """Emit a terminal ``done`` SSE event and clean up the Redis token stream.

    Called once after the entire graph finishes (success, failure, or
    cancellation) so the frontend knows the session is over and can close
    the SSE connection.

    Args:
        thread_id: LangGraph thread UUID.
        status:    Final session status: ``"completed"``, ``"failed"``, or
                   ``"cancelled"``.
        report:    Optional short excerpt of the final report (first 500
                   chars).
    """
    await pg_notify(
        thread_id,
        {
            "event": "done",
            "status": status,
            "data": report[:500] if report else "",
        },
    )
    await delete_stream(thread_id)


__all__ = [
    "create_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    "emit_done",
]
