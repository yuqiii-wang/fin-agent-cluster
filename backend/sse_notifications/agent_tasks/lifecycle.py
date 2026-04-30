"""Task lifecycle SSE notifications — DB writes + Redis publish.

Every public function in this module follows the same pattern:
  1. Write the new task state to ``fin_agents.tasks`` in PostgreSQL.
  2. Commit the transaction.
  3. Publish directly to Redis Pub/Sub so SSE subscribers receive
     an authoritative, durable event payload.
  4. Record the step in the Redis task-ACK store for delivery tracking.

Only lifecycle events travel through this path.  Token events use the Redis
Streams path (see :mod:`backend.sse_notifications.agent_tasks.token_stream`).

``AgentTask`` is imported lazily inside each function to break the circular
dependency:
  ``sse_notifications`` ← ``backend.graph`` (package) ← agents ← ``sse_notifications``
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update

from backend.db.postgres.engine import get_session_factory
from backend.db.redis.session.task_ack_store import record_task_step
from backend.sse_notifications.channel import publish_lifecycle

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
    extra_payload: Optional[dict] = None,
) -> int:
    """Insert a running task record in DB and emit a ``started`` SSE notification.

    Records a delivery step in the Redis task-ACK store after commit.

    Args:
        thread_id:         LangGraph thread UUID.
        task_key:          Full dot-separated task key.
        node_execution_id: FK to the parent ``node_executions`` row (optional).
        provider:          LLM provider name for the ``started`` payload (optional).
        extra_payload:     Additional fields merged into the ``started`` event
                           payload (e.g. ``node_id``, ``leaf_node_id``,
                           ``stream_id``).

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
        # Notify inside the transaction — PostgreSQL delivers the NOTIFY
        # atomically at COMMIT, so subscribers always see the task row.
        payload: dict = {
            "event": "started",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
        }
        if provider:
            payload["provider"] = provider
        if extra_payload:
            payload.update(extra_payload)
        logger.info(
            "[task_lifecycle] publish event=started task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await session.commit()
    # Publish to Redis Pub/Sub after commit — DB row is now durable.
    await publish_lifecycle(thread_id, payload)
    # Record step and push ack-store entry AFTER commit.
    await record_task_step(thread_id, task_id, "digesting")

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
        logger.info(
            "[task_lifecycle] publish event=completed task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await session.commit()
    # Publish to Redis Pub/Sub after commit — DB row is now durable.
    await publish_lifecycle(
        thread_id,
        {
            "event": "completed",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
            "output": output_val,
        },
    )
    # Record step and push ack-store entry after commit.
    await record_task_step(thread_id, task_id, "completed")

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
    error_code: str | None = None,
) -> None:
    """Mark a task failed in DB and emit a ``failed`` SSE notification.

    Args:
        thread_id:  LangGraph thread UUID.
        task_id:    DB primary key of the task row.
        task_key:   Full dot-separated task key.
        error:      Error message string (truncated to 500 chars in output).
        error_code: Optional structured error code from
                    :mod:`backend.streaming.lifecycle.errors`.  When provided
                    the code and its human-readable description are embedded in
                    the SSE payload so the frontend can show a rich tooltip
                    without an extra API round-trip.
    """
    from backend.graph.models import AgentTask  # deferred to avoid circular import
    from backend.streaming.errors import STREAMING_ERRORS  # deferred

    node = _node_name(task_key)
    output_val: dict = {"error": error[:500]}
    if error_code:
        output_val["error_code"] = error_code
        desc = STREAMING_ERRORS.get(error_code)
        if desc:
            output_val["error_description"] = desc
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
        logger.info(
            "[task_lifecycle] publish event=failed task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await session.commit()
    # Publish to Redis Pub/Sub after commit — DB row is now durable.
    _failed_payload: dict = {
        "event": "failed",
        "task_id": task_id,
        "node_name": node,
        "task_key": task_key,
        "output": output_val,
    }
    await publish_lifecycle(thread_id, _failed_payload)
    # Record step and push ack-store entry after commit.
    await record_task_step(thread_id, task_id, "failed")

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
        logger.info(
            "[task_lifecycle] publish event=cancelled task_id=%d task_key=%s node=%s thread_id=%s",
            task_id,
            task_key,
            node,
            thread_id,
        )
        await session.commit()
    # Publish to Redis Pub/Sub after commit — DB row is now durable.
    await publish_lifecycle(
        thread_id,
        {
            "event": "cancelled",
            "task_id": task_id,
            "node_name": node,
            "task_key": task_key,
            "output": output_val,
        },
    )
    # Record step and push ack-store entry after commit.
    await record_task_step(thread_id, task_id, "cancelled")

    logger.info(
        "[task_lifecycle] cancelled task_id=%d key=%s node=%s thread_id=%s",
        task_id,
        task_key,
        node,
        thread_id,
    )


async def emit_done(
    thread_id: str,
    status: str,
    report: str = "",
    error_code: str | None = None,
) -> None:
    """Emit a terminal ``done`` SSE event for the thread.

    Called once after the entire graph finishes (success, failure, cancellation,
    or timeout) so the frontend knows the session is over and can close the SSE
    connection.  The ``status`` value is forwarded verbatim so the frontend can
    distinguish ``"timeout"`` from a regular ``"cancelled"`` action.

    The Redis token stream (``tokens:{thread_id}``) is intentionally **not**
    deleted here.  It is cleaned up by
    :func:`~backend.db.redis.lock_manager.session_cleanup.cleanup_thread_session`
    at true thread lifecycle end (after ``emit_done`` returns in the runner)
    so that any in-flight SSE drain can still read buffered tokens.

    Args:
        thread_id:  LangGraph thread UUID.
        status:     Final session status emitted to the client.  Standard values:
                    ``"completed"``, ``"failed"``, ``"cancelled"``, ``"timeout"``.
        report:     Optional short excerpt of the final report (first 500 chars).
        error_code: Optional structured error code from
                    :mod:`backend.streaming.lifecycle.errors`.  Only meaningful
                    when ``status`` is ``"failed"``; embedded in the ``done``
                    payload so the frontend can surface a rich error tooltip.
    """
    from backend.streaming.errors import STREAMING_ERRORS  # deferred

    _done_payload: dict = {"event": "done", "status": status, "data": report[:500] if report else ""}
    if error_code:
        _done_payload["error_code"] = error_code
        desc = STREAMING_ERRORS.get(error_code)
        if desc:
            _done_payload["error_description"] = desc
    logger.info(
        "[task_lifecycle] publish event=done status=%s thread_id=%s",
        status,
        thread_id,
    )
    await publish_lifecycle(thread_id, _done_payload)
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
