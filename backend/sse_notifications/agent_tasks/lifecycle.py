"""Task lifecycle SSE notifications — DB writes + pg_notify emission.

Every public function in this module follows the same pattern:
  1. Write the new task state to ``fin_agents.tasks`` in PostgreSQL.
  2. Append a row to ``fin_agents.streamings`` (status + elapsed_ms only).
  3. Commit the transaction.
  4. Fire ``pg_notify`` on the thread's channel so SSE subscribers receive
     an authoritative, durable event payload.

Only lifecycle events travel through this path.  Token events use the Redis
Streams path (see :mod:`backend.sse_notifications.agent_tasks.token_stream`).

``AgentTask`` / ``Streaming`` are imported lazily inside each function to break
the circular dependency:
  ``sse_notifications`` ← ``backend.graph`` (package) ← agents ← ``sse_notifications``
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres.engine import get_session_factory
from backend.db.redis.publisher import delete_stream, push_pending_notify
from backend.sse_notifications.channel import pg_notify, pg_notify_in_session

logger = logging.getLogger(__name__)


def _node_name(task_key: str) -> str:
    """Extract the agent node name from a dot-separated task key.

    Args:
        task_key: Full task key, e.g. ``"market_data_collector.ohlcv.15min"``.

    Returns:
        First dot-separated segment, e.g. ``"market_data_collector"``.
    """
    return task_key.split(".")[0]


async def _append_step(
    session: AsyncSession,
    task_id: int,
    thread_id: str,
    status: str,
) -> None:
    """Append a :class:`StreamingStatus` row inside an already-open session.

    The row is added to the session but not yet committed — the caller is
    responsible for committing.

    Args:
        session:   Open SQLAlchemy async session (must be in active txn).
        task_id:   FK to the parent ``fin_agents.tasks`` row.
        thread_id: FK to the parent ``fin_agents.user_queries`` row.
        status:    Status the task transitioned INTO (matches streamings CHECK).
    """
    from backend.graph.models import Streaming  # deferred to avoid circular import

    session.add(
        Streaming(
            task_id=task_id,
            thread_id=thread_id,
            status=status,
        )
    )


async def create_task(
    thread_id: str,
    task_key: str,
    node_execution_id: Optional[int] = None,
    provider: Optional[str] = None,
) -> int:
    """Insert a running task record in DB and emit a ``started`` SSE notification.

    Also appends an initial ``sending`` step to ``fin_agents.streamings``
    to mark the task start in the audit log.

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
    from backend.graph.models import AgentTask, Streaming  # deferred to avoid circular import

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
        # Initial step: marks the task start in the audit log.
        session.add(
            Streaming(
                task_id=task_id,
                thread_id=thread_id,
                status="digesting",
            )
        )
        # Notify inside the transaction — PostgreSQL delivers the NOTIFY
        # atomically at COMMIT, so subscribers always see the step row.
        payload: dict = {
            "event": "started",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
        }
        if provider:
            payload["provider"] = provider
        logger.info(
            "[task_lifecycle] pg_notify event=started task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await pg_notify_in_session(session, thread_id, payload)
        await session.commit()
    # Push ack-store entry AFTER commit so the data is durable before we
    # advertise the event as pending.
    await push_pending_notify(thread_id, "started", task_id, json.dumps(payload))

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

    Appends a ``completed`` step to ``fin_agents.streamings`` with the
    wall-clock elapsed time from task creation.

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
        await _append_step(session, task_id, thread_id, "completed")
        logger.info(
            "[task_lifecycle] pg_notify event=completed task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await pg_notify_in_session(
            session,
            thread_id,
            {
                "event": "completed",
                "task_id": task_id,
                "node_name": node,
                "task_key": task_key,
                "output": output_val,
            },
        )
        await session.commit()
    # Push ack-store entry after commit.
    await push_pending_notify(
        thread_id, "completed", task_id,
        json.dumps({"event": "completed", "task_id": task_id, "node_name": node, "task_key": task_key, "output": output_val}),
    )

    logger.info(
        "[task_lifecycle] completed task_id=%d key=%s node=%s thread_id=%s output_keys=%s",
        task_id,
        task_key,
        node,
        thread_id,
        list(output_val.keys()),
    )


async def fail_task(
    thread_id: str,
    task_id: int,
    task_key: str,
    error: str,
) -> None:
    """Mark a task failed in DB and emit a ``failed`` SSE notification.

    Appends a ``failed`` step to ``fin_agents.streamings``.

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
        await _append_step(session, task_id, thread_id, "failed")
        logger.info(
            "[task_lifecycle] pg_notify event=failed task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await pg_notify_in_session(
            session,
            thread_id,
            {
                "event": "failed",
                "task_id": task_id,
                "node_name": node,
                "task_key": task_key,
                "output": output_val,
            },
        )
        await session.commit()
    # Push ack-store entry after commit.
    await push_pending_notify(
        thread_id, "failed", task_id,
        json.dumps({"event": "failed", "task_id": task_id, "node_name": node, "task_key": task_key, "output": output_val}),
    )

    logger.warning(
        "[task_lifecycle] failed task_id=%d key=%s node=%s error=%r thread_id=%s",
        task_id,
        task_key,
        node,
        error[:120],
        thread_id,
    )


async def cancel_task(
    thread_id: str,
    task_id: int,
    task_key: str,
) -> None:
    """Mark a task cancelled in DB and emit a ``cancelled`` SSE notification.

    Appends a ``cancelled`` step to ``fin_agents.streamings``.

    Args:
        thread_id: LangGraph thread UUID.
        task_id:   DB primary key of the task row.
        task_key:  Full dot-separated task key.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import

    node = _node_name(task_key)
    # Empty output — the LangGraph node treats this task's contribution as absent
    # and can continue gathering results from other tasks in the same node.
    output_val: dict = {}
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
        await _append_step(session, task_id, thread_id, "cancelled")
        logger.info(
            "[task_lifecycle] pg_notify event=cancelled task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await pg_notify_in_session(
            session,
            thread_id,
            {
                "event": "cancelled",
                "task_id": task_id,
                "node_name": node,
                "task_key": task_key,
                "output": output_val,
            },
        )
        await session.commit()
    # Push ack-store entry after commit.
    await push_pending_notify(
        thread_id, "cancelled", task_id,
        json.dumps({"event": "cancelled", "task_id": task_id, "node_name": node, "task_key": task_key, "output": output_val}),
    )

    logger.info(
        "[task_lifecycle] cancelled task_id=%d key=%s node=%s thread_id=%s",
        task_id,
        task_key,
        node,
        thread_id,
    )


async def emit_done(thread_id: str, status: str, report: str = "") -> None:
    """Emit a terminal ``done`` SSE event and clean up the Redis token stream.

    Called once after the entire graph finishes (success, failure, cancellation,
    or timeout) so the frontend knows the session is over and can close the SSE
    connection.  The ``status`` value is forwarded verbatim so the frontend can
    distinguish ``"timeout"`` from a regular ``"cancelled"`` action.

    Args:
        thread_id: LangGraph thread UUID.
        status:    Final session status emitted to the client.  Standard values:
                   ``"completed"``, ``"failed"``, ``"cancelled"``, ``"timeout"``.
        report:    Optional short excerpt of the final report (first 500 chars).
    """
    _done_payload = {"event": "done", "status": status, "data": report[:500] if report else ""}
    logger.info(
        "[task_lifecycle] pg_notify event=done status=%s thread_id=%s",
        status,
        thread_id,
    )
    await pg_notify(thread_id, _done_payload)
    # Push ack-store entry so the SSE generator can recover if pg_notify was lost.
    await push_pending_notify(thread_id, "done", None, json.dumps(_done_payload))
    await delete_stream(thread_id)
    logger.info(
        "[task_lifecycle] done_emitted status=%s thread_id=%s",
        status,
        thread_id,
    )


__all__ = [
    "create_task",
    "complete_task",
    "fail_task",
    "cancel_task",
    "emit_done",
]
