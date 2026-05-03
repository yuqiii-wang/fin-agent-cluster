"""Governance lifecycle publisher — propagate end/cancel events down the hierarchy.

When a LangGraph thread ends naturally or is cancelled, this module traverses
the governance registry (thread → nodes → streams) and emits a terminal
lifecycle event for every leaf stream still registered.

A stream that already deregistered itself has completed normally and receives
no additional event — only orphaned or interrupted streams are notified here.

This module is stream-type-agnostic: any node that registers leaf work in the
governance registry benefits from automatic terminal propagation on thread
cancel or completion.

Cancel scoping
--------------
* :func:`publish_governance_end`   — thread-level; closes all governed IDs.
* :func:`publish_node_cancel`      — node-level; cascades to all tasks + streams under the node.
* :func:`publish_task_cancel`      — task-level; cascades to all streams under the task.
"""

from __future__ import annotations

import logging

from backend.graph.governance.registry import (
    close_governed_ids,
    get_streams_for_task,
    get_streams_for_thread,
    get_tasks_for_node,
    request_task_cancel,
)
from backend.sse_notifications.stream.notifications import emit_stream_stopped
from backend.sse_notifications.task.control import signal_task_control

logger = logging.getLogger(__name__)


async def publish_governance_end(
    thread_id: str,
    reason: str = "cancelled",
    duration_secs: int = 0,
) -> None:
    """Traverse the governance hierarchy, emit terminal events, then cascade-close all governed IDs.

    Called by the graph runner and cancel endpoint after the thread transitions
    to a terminal state.  Emits ``stream_stopped`` for every leaf stream still
    present in the registry so the frontend receives a clean terminal event
    even when the Celery worker never had a chance to deregister.

    After emitting all terminal events, calls
    :func:`~backend.graph.governance.registry.close_governed_ids` to delete
    every Redis key registered under *thread_id* (stream meta hashes, task-
    streams sets, node-tasks sets, status hashes, and cancel keys) leaving the
    governance registry fully clean.

    Only streams still in the governance registry are notified — streams that
    already called :func:`~backend.graph.governance.registry.deregister_stream`
    completed normally and do not need an additional event.

    Args:
        thread_id:     LangGraph thread UUID (top-level scope).
        reason:        Terminal reason — ``"cancelled"``, ``"completed"``, or
                       ``"failed"``.  Embedded in the ``stream_stopped`` payload
                       so the frontend can distinguish clean ends from forced stops.
        duration_secs: Configured max duration in seconds (0 = unknown).
    """
    pairs = await get_streams_for_thread(thread_id)
    if not pairs:
        logger.debug(
            "[governance] publish_governance_end no live streams thread_id=%s reason=%s",
            thread_id, reason,
        )
    else:
        logger.info(
            "[governance] publish_governance_end thread_id=%s reason=%s streams=%d",
            thread_id, reason, len(pairs),
        )
        for node_id, task_id, stream_id in pairs:
            try:
                await emit_stream_stopped(
                    thread_id=thread_id,
                    stream_id=stream_id,
                    node_id=node_id,
                    task_id=task_id,
                    duration_secs=duration_secs,
                    total_published=0,
                    ingest_ms=0,
                )
                logger.debug(
                    "[governance] stream_stopped emitted stream_id=%s task_id=%s node_id=%s thread_id=%s",
                    stream_id, task_id, node_id, thread_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[governance] stream_stopped emit failed stream_id=%s task_id=%s node_id=%s thread_id=%s: %s",
                    stream_id, task_id, node_id, thread_id, exc,
                )

    # Cascade-close all governed IDs regardless of whether streams were live.
    await close_governed_ids(thread_id)
    logger.info(
        "[governance] governed_ids_closed thread_id=%s reason=%s",
        thread_id, reason,
    )


async def publish_node_cancel(thread_id: str, node_id: str) -> None:
    """Cascade-cancel a node: signal all tasks and emit ``stream_stopped`` for live streams.

    Called after the node-level cancel signal is set in Redis and the DB rows
    are updated.  Iterates every task registered under *node_id*, sets the Redis
    cancel signal for each task (so polling-based workers pick it up), signals
    any in-process streaming loop via :func:`signal_task_control`, and emits
    ``stream_stopped`` for every leaf stream still live in the registry.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing and SSE routing).
        node_id:   Node execution UUID whose subtree should be cancelled.
    """
    task_ids = await get_tasks_for_node(thread_id, node_id)
    if not task_ids:
        logger.debug(
            "[governance] publish_node_cancel no live tasks node_id=%s thread_id=%s",
            node_id, thread_id,
        )
        return

    logger.info(
        "[governance] publish_node_cancel node_id=%s thread_id=%s tasks=%d",
        node_id, thread_id, len(task_ids),
    )
    for task_id in task_ids:
        # Cascade Redis cancel signal to each task.
        await request_task_cancel(thread_id, task_id, node_id=node_id)
        # Signal any in-process streaming loop running in this process.
        signal_task_control(task_id, "cancel")
        # Emit stream_stopped for every live stream under this task.
        await _emit_task_streams_stopped(thread_id, node_id, task_id)


async def publish_task_cancel(thread_id: str, node_id: str, task_id: str) -> None:
    """Cascade-cancel a task: signal the in-process loop and emit ``stream_stopped``.

    Called after the task-level cancel signal is set in Redis.  Signals the
    in-process streaming loop (if any) and emits ``stream_stopped`` for every
    leaf stream still registered under *task_id*.

    Args:
        thread_id: LangGraph thread UUID (used for shard routing and SSE routing).
        node_id:   Parent node UUID (for SSE routing context).
        task_id:   Task invocation UUID to cancel.
    """
    # Signal any in-process streaming loop running in this process.
    signal_task_control(task_id, "cancel")
    # Emit stream_stopped for every live stream under this task.
    await _emit_task_streams_stopped(thread_id, node_id, task_id)
    logger.info(
        "[governance] publish_task_cancel task_id=%s node_id=%s thread_id=%s",
        task_id, node_id, thread_id,
    )


async def _emit_task_streams_stopped(thread_id: str, node_id: str, task_id: str) -> None:
    """Emit ``stream_stopped`` for every live stream registered under *task_id*.

    Internal helper shared by :func:`publish_node_cancel` and
    :func:`publish_task_cancel`.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Parent node UUID for event context.
        task_id:   Task invocation UUID.
    """
    stream_ids = await get_streams_for_task(thread_id, task_id)
    for stream_id in stream_ids:
        try:
            await emit_stream_stopped(
                thread_id=thread_id,
                stream_id=stream_id,
                node_id=node_id,
                task_id=task_id,
                duration_secs=0,
                total_published=0,
                ingest_ms=0,
            )
            logger.debug(
                "[governance] stream_stopped emitted stream_id=%s task_id=%s node_id=%s thread_id=%s",
                stream_id, task_id, node_id, thread_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[governance] stream_stopped emit failed stream_id=%s task_id=%s node_id=%s thread_id=%s: %s",
                stream_id, task_id, node_id, thread_id, exc,
            )


__all__ = [
    "publish_governance_end",
    "publish_node_cancel",
    "publish_task_cancel",
]
